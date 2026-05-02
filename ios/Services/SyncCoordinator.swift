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

        let syncState = syncStateStore.load()
        self.hasPendingSync = syncState.hasPendingAutoSync
        self.lastSyncAttemptAt = syncState.lastSyncAttemptAt
    }

    func start() {
        guard !hasStarted else { return }

        hasStarted = true
        print("sync_coordinator_start")

        registerHealthKitObservers()
        HealthKitService.shared.enableObservers()
        triggerSync(reason: .appLaunch)
    }

    func handleAppBecameActive() {
        triggerSync(reason: hasPendingSync ? .pendingRetry : .appBecameActive)
    }

    func handleHealthKitUpdate(reason: AutoSyncReason) {
        triggerSyncDebounced(reason: hasPendingSync ? .pendingRetry : reason)
    }

    func triggerSyncDebounced(reason: AutoSyncReason) {
        debounceWorkItem?.cancel()

        let workItem = DispatchWorkItem { [weak self] in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.triggerSync(reason: reason)
            }
        }

        debounceWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + debounceInterval, execute: workItem)
    }

    func triggerSync(reason: AutoSyncReason) {
        print("auto_sync_triggered reason=\(reason.rawValue)")

        if isSyncRunning {
            shouldSyncAgainAfterCurrentRun = true
            print("auto_sync_skipped_already_running reason=\(reason.rawValue)")
            return
        }

        if shouldThrottleLifecycleSync(for: reason) {
            print("auto_sync_skipped_throttled reason=\(reason.rawValue)")
            return
        }

        isSyncRunning = true
        lastSyncAttemptAt = Date()

        saveSyncState { syncState in
            syncState.lastSyncAttemptAt = self.lastSyncAttemptAt
            syncState.lastErrorMessage = nil
        }

        print("auto_sync_started reason=\(reason.rawValue)")

        syncService.performIncrementalSync { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                let hasPayload = data.payload != nil
                print("auto_sync_incremental_result hasPayload=\(hasPayload)")

                guard let payload = data.payload else {
                    print("auto_sync_noop")
                    self.hasPendingSync = false
                    self.saveSyncState { syncState in
                        syncState.hasPendingAutoSync = false
                        syncState.lastErrorMessage = nil
                        syncState.lastSyncMode = .incremental
                    }
                    self.finishSync(success: true)
                    return
                }

                print("auto_sync_send_started")
                self.syncService.sendPayload(payload, userID: self.backendUserID) { [weak self] sendResult in
                    guard let self else { return }

                    switch sendResult {
                    case .success(let response):
                        print(
                            """
                            auto_sync_send_finished \
                            affected_dates=\(response.affectedDates.count) \
                            recovery=\(response.recoveryDaysRecomputed) \
                            readiness=\(response.readinessDaysRecomputed)
                            """
                        )

                        self.hasPendingSync = false
                        self.saveSyncState { syncState in
                            syncState.lastSuccessfulSyncAt = Date()
                            syncState.lastPayloadGeneratedAt = Date()
                            syncState.lastErrorMessage = nil
                            syncState.lastSentItemCount = self.payloadItemCount(payload)
                            syncState.lastSyncMode = .incremental
                            syncState.hasPendingAutoSync = false
                        }
                        self.finishSync(success: true)

                    case .failure(let error):
                        print("auto_sync_failed reason=\(reason.rawValue) error=\(error.localizedDescription)")
                        self.markPendingSync(errorMessage: error.localizedDescription)
                        self.finishSync(success: false)
                    }
                }

            case .failure(let error):
                print("auto_sync_failed reason=\(reason.rawValue) error=\(error.localizedDescription)")
                self.markPendingSync(errorMessage: error.localizedDescription)
                self.finishSync(success: false)
            }
        }
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
        hasPendingSync = true
        saveSyncState { syncState in
            syncState.lastErrorMessage = errorMessage
            syncState.hasPendingAutoSync = true
            syncState.lastSyncMode = .incremental
        }
    }

    private func finishSync(success: Bool) {
        isSyncRunning = false
        notificationCenter.post(name: .syncStateDidChange, object: nil)

        if success {
            notificationCenter.post(name: .autoSyncDidFinish, object: nil)
        }

        if shouldSyncAgainAfterCurrentRun {
            shouldSyncAgainAfterCurrentRun = false
            triggerSync(reason: .pendingRetry)
        }
    }

    private func saveSyncState(_ mutate: (inout SyncState) -> Void) {
        var syncState = syncStateStore.load()
        mutate(&syncState)
        syncStateStore.save(syncState)

        let lastSuccessfulSyncAt = syncState.lastSuccessfulSyncAt?.description ?? "nil"
        let lastSyncAttemptAt = syncState.lastSyncAttemptAt?.description ?? "nil"

        print(
            "sync_state_saved " +
            "lastSuccessfulSyncAt=\(lastSuccessfulSyncAt) " +
            "lastSyncAttemptAt=\(lastSyncAttemptAt) " +
            "hasPendingAutoSync=\(syncState.hasPendingAutoSync)"
        )
    }

    private func payloadItemCount(_ payload: HealthSyncPayload) -> Int {
        payload.sleepNights.count +
        payload.restingHeartRateDaily.count +
        payload.hrvSamples.count +
        (payload.latestWeight == nil ? 0 : 1)
    }
}
