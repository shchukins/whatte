import Foundation

enum AutoSyncReason: String {
    case appLaunch = "app_launch"
    case appBecameActive = "app_became_active"
    case healthKitHRVUpdated = "healthkit_hrv_updated"
    case healthKitRestingHRUpdated = "healthkit_resting_hr_updated"
    case healthKitSleepUpdated = "healthkit_sleep_updated"
    case pendingRetry = "pending_retry"
}

@MainActor
final class SyncCoordinator {
    static let shared = SyncCoordinator()

    private let notificationCenter: NotificationCenter
    private let syncService: SyncService
    private let syncStateStore: SyncStateStore
    private let debounceInterval: TimeInterval = 5
    private let lifecycleThrottleInterval: TimeInterval = 10
    private let backendUserID = "sergey"

    private var observerTokens: [NSObjectProtocol] = []
    private var hasStarted = false
    private var shouldSyncAgainAfterCurrentRun = false

    private(set) var isSyncRunning = false
    private(set) var hasPendingSync: Bool
    private(set) var lastSyncAttemptAt: Date?
    private var debounceWorkItem: DispatchWorkItem?

    private init() {
        let notificationCenter = NotificationCenter.default
        let syncService = SyncService.shared
        let syncStateStore = SyncStateStore.shared

        self.notificationCenter = notificationCenter
        self.syncService = syncService
        self.syncStateStore = syncStateStore
        self.hasPendingSync = syncStateStore.load().hasPendingAutoSync
    }

    func start() {
        guard !hasStarted else { return }

        hasStarted = true
        registerHealthKitObservers()
        HealthKitService.shared.enableObservers()
        triggerSync(reason: .appLaunch)
    }

    func triggerSync(reason: AutoSyncReason) {
        if isSyncRunning {
            shouldSyncAgainAfterCurrentRun = true
            print("auto_sync_skipped_already_running reason=\(reason.rawValue)")
            return
        }

        if shouldThrottleLifecycleSync(for: reason) {
            return
        }

        isSyncRunning = true
        lastSyncAttemptAt = Date()

        print("auto_sync_started reason=\(reason.rawValue)")

        syncService.performIncrementalSync { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                if let payload = data.payload {
                    self.syncService.sendPayload(payload, userID: self.backendUserID) { [weak self] sendResult in
                        guard let self else { return }

                        switch sendResult {
                        case .success(let response):
                            var syncState = self.syncStateStore.load()
                            syncState.lastSuccessfulSyncAt = Date()
                            syncState.lastPayloadGeneratedAt = Date()
                            syncState.lastErrorMessage = nil
                            syncState.lastSentItemCount = self.payloadItemCount(payload)
                            syncState.lastSyncMode = .incremental
                            syncState.hasPendingAutoSync = false
                            self.syncStateStore.save(syncState)

                            self.hasPendingSync = false

                            print(
                                """
                                auto_sync_finished reason=\(reason.rawValue) \
                                affected_dates=\(response.affectedDates.count) \
                                recovery=\(response.recoveryDaysRecomputed) \
                                readiness=\(response.readinessDaysRecomputed)
                                """
                            )

                            self.finishSync(reloadReadiness: true)

                        case .failure(let error):
                            self.markPendingSync(errorMessage: error.localizedDescription)
                            print("auto_sync_failed reason=\(reason.rawValue) error=\(error.localizedDescription)")
                            self.finishSync(reloadReadiness: false)
                        }
                    }
                    return
                }

                var syncState = self.syncStateStore.load()
                syncState.lastErrorMessage = nil
                syncState.lastSyncMode = .incremental
                syncState.hasPendingAutoSync = false
                self.syncStateStore.save(syncState)

                self.hasPendingSync = false

                print("auto_sync_finished reason=\(reason.rawValue) no_new_data=true")
                self.finishSync(reloadReadiness: true)

            case .failure(let error):
                self.markPendingSync(errorMessage: error.localizedDescription)
                print("auto_sync_failed reason=\(reason.rawValue) error=\(error.localizedDescription)")
                self.finishSync(reloadReadiness: false)
            }
        }
    }

    func triggerSyncDebounced(reason: AutoSyncReason) {
        debounceWorkItem?.cancel()

        let workItem = DispatchWorkItem { [weak self] in
            Task { @MainActor in
                self?.triggerSync(reason: reason)
            }
        }

        debounceWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + debounceInterval, execute: workItem)
    }

    func handleAppBecameActive() {
        let reason: AutoSyncReason = hasPendingSync ? .pendingRetry : .appBecameActive
        triggerSync(reason: reason)
    }

    func handleHealthKitUpdate(reason: AutoSyncReason) {
        let resolvedReason: AutoSyncReason = hasPendingSync ? .pendingRetry : reason
        triggerSyncDebounced(reason: resolvedReason)
    }

    private func registerHealthKitObservers() {
        observerTokens.append(
            notificationCenter.addObserver(
                forName: .healthKitHRVUpdated,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.handleHealthKitUpdate(reason: .healthKitHRVUpdated)
                }
            }
        )

        observerTokens.append(
            notificationCenter.addObserver(
                forName: .healthKitRestingHRUpdated,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.handleHealthKitUpdate(reason: .healthKitRestingHRUpdated)
                }
            }
        )

        observerTokens.append(
            notificationCenter.addObserver(
                forName: .healthKitSleepUpdated,
                object: nil,
                queue: .main
            ) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.handleHealthKitUpdate(reason: .healthKitSleepUpdated)
                }
            }
        )
    }

    private func shouldThrottleLifecycleSync(for reason: AutoSyncReason) -> Bool {
        guard reason == .appLaunch || reason == .appBecameActive else {
            return false
        }

        guard !hasPendingSync, let lastSyncAttemptAt else {
            return false
        }

        return Date().timeIntervalSince(lastSyncAttemptAt) < lifecycleThrottleInterval
    }

    private func markPendingSync(errorMessage: String) {
        var syncState = syncStateStore.load()
        syncState.lastErrorMessage = errorMessage
        syncState.hasPendingAutoSync = true
        syncStateStore.save(syncState)
        hasPendingSync = true
    }

    private func finishSync(reloadReadiness: Bool) {
        isSyncRunning = false

        notificationCenter.post(name: .syncStateDidChange, object: nil)

        if reloadReadiness {
            notificationCenter.post(name: .autoSyncDidFinish, object: nil)
        }

        if shouldSyncAgainAfterCurrentRun {
            shouldSyncAgainAfterCurrentRun = false
            triggerSync(reason: .pendingRetry)
        }
    }

    private func payloadItemCount(_ payload: HealthSyncPayload) -> Int {
        payload.sleepNights.count +
        payload.restingHeartRateDaily.count +
        payload.hrvSamples.count +
        (payload.latestWeight == nil ? 0 : 1)
    }
}
