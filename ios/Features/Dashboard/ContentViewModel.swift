//
//  ContentViewModel.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation
import Observation

@Observable
final class ContentViewModel {
    private static let backfillStartDate: Date = {
        let calendar = Calendar(identifier: .gregorian)
        return calendar.date(from: DateComponents(year: 2026, month: 5, day: 23)) ?? Date.distantPast
    }()
    private static let hasRequestedPermissionsKey = "healthkit_read_permissions_requested"

    // MARK: - Loaded HealthKit data used by sync pipeline

    var weightSamples: [WeightSample] = []
    var restingHRSamples: [RestingHRSample] = []
    var hrvSamples: [HRVSample] = []
    var sleepSamples: [SleepSample] = []
    var sleepNightAggregates: [SleepNightAggregate] = []

    // MARK: - Incremental / delta data

    var newHRVSamples: [HRVSample] = []
    var newRestingHRSamples: [RestingHRSample] = []
    var newSleepNightAggregates: [SleepNightAggregate] = []

    // MARK: - Readiness

    var todayReadiness: ReadinessDailyResponse?
    var readinessHistory: [ReadinessHistoryItem] = []
    var readinessErrorMessage: String?

    // MARK: - UI / runtime state

    var statusMessage: String = "Idle"
    var authorizationItems: [(name: String, status: String)] = []
    var payloadSummary: String = ""
    var payloadPreview: String = ""
    var syncState: SyncState = SyncStateStore.shared.load()
    var isSyncInProgress: Bool = false

    let backendUserID: String = "sergey"
    private var hasRequestedHealthPermissions = UserDefaults.standard.bool(forKey: hasRequestedPermissionsKey)

    // MARK: - Startup logic

    private var hasPerformedInitialSync = false

    // MARK: - Sync state

    func reloadSyncState() {
        syncState = SyncStateStore.shared.load()
    }

    func saveSyncState() {
        SyncStateStore.shared.save(syncState)
    }

    // MARK: - Permissions

    func requestPermissions() {
        hasRequestedHealthPermissions = true
        UserDefaults.standard.set(true, forKey: Self.hasRequestedPermissionsKey)

        HealthKitService.shared.requestAuthorization { [weak self] result in
            guard let self else { return }

            switch result {
            case .success:
                self.statusMessage = "Authorization successful"
                self.refreshStatuses()

            case .failure(let error):
                self.statusMessage = error.localizedDescription
                self.refreshStatuses()
            }
        }
    }

    func refreshStatuses() {
        authorizationItems = [
            (name: "HRV", status: readStatus(hasData: !hrvSamples.isEmpty)),
            (name: "Resting HR", status: readStatus(hasData: !restingHRSamples.isEmpty)),
            (name: "Sleep", status: readStatus(hasData: !sleepNightAggregates.isEmpty || !sleepSamples.isEmpty)),
            (name: "Weight", status: readStatus(hasData: !weightSamples.isEmpty))
        ]
    }

    func resetSyncState() {
        syncState = .empty
        SyncStateStore.shared.clear()
        payloadSummary = ""
        payloadPreview = ""
        statusMessage = "Sync state reset"
        refreshStatuses()
    }

    // MARK: - Sending

    func sendPayload(
        _ payload: HealthSyncPayload,
        mode: SyncMode,
        completion: @escaping () -> Void
    ) {
        statusMessage = "Sending..."

        let itemCount = payloadItemCount(payload)

        SyncService.shared.sendPayload(
            payload,
            userID: backendUserID
        ) { [weak self] result in
            guard let self else {
                completion()
                return
            }

            switch result {
            case .success(let response):
                self.statusMessage = """
                \(self.syncSuccessTitle(for: mode))
                dates: \(response.affectedDates.count)
                recovery: \(response.recoveryDaysRecomputed)
                readiness: \(response.readinessDaysRecomputed)
                """

                self.syncState.lastSuccessfulSyncAt = Date()
                self.syncState.lastPayloadGeneratedAt = Date()
                self.syncState.lastErrorMessage = nil
                self.syncState.lastSentItemCount = itemCount
                self.syncState.lastSyncMode = mode
                self.saveSyncState()
                self.loadTodayReadiness()

            case .failure(let error):
                self.statusMessage = "Send error: \(error.localizedDescription)"
                self.syncState.lastPayloadGeneratedAt = Date()
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
            }

            completion()
        }
    }

    // MARK: - Full sync

    func performFullSync(
        completion: @escaping (Result<FullSyncData, Error>) -> Void
    ) {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running full sync..."

        SyncService.shared.performFullSync { [weak self] result in
            guard let self else {
                completion(result)
                return
            }

            switch result {
            case .success(let data):
                completion(.success(data))

            case .failure(let error):
                self.statusMessage = "Full sync error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
                completion(.failure(error))
            }
        }
    }

    func performBackfill(
        completion: @escaping (Result<FullSyncData, Error>) -> Void
    ) {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running backfill since 2026-05-23..."

        SyncService.shared.performBackfill(from: Self.backfillStartDate) { [weak self] result in
            guard let self else {
                completion(result)
                return
            }

            switch result {
            case .success(let data):
                completion(.success(data))

            case .failure(let error):
                self.statusMessage = "Backfill error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
                completion(.failure(error))
            }
        }
    }

    // MARK: - Incremental sync

    func performIncrementalSync(
        completion: @escaping (Result<IncrementalSyncData, Error>) -> Void
    ) {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running incremental sync..."

        SyncService.shared.performIncrementalSync { [weak self] result in
            guard let self else {
                completion(result)
                return
            }

            switch result {
            case .success(let data):
                if payloadItemCount(from: data) == 0 {
                    self.statusMessage = "Incremental sync: no new data"
                    self.syncState.lastErrorMessage = nil
                    self.syncState.lastSyncMode = .incremental
                    self.saveSyncState()
                    self.isSyncInProgress = false
                }

                completion(.success(data))

            case .failure(let error):
                self.statusMessage = "Incremental sync error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
                completion(.failure(error))
            }
        }
    }

    // MARK: - Initial sync

    func performInitialSyncIfNeeded(
        completion: @escaping (Result<IncrementalSyncData, Error>) -> Void
    ) {
        guard !hasPerformedInitialSync else { return }
        guard !isSyncInProgress else { return }

        hasPerformedInitialSync = true
        statusMessage = "Initial sync..."

        performIncrementalSync { result in
            completion(result)
        }
    }

    // MARK: - Sample reads / payload

    func readSampleData() {
        statusMessage = "Reading sample data..."

        HealthKitService.shared.fetchLatestWeightSample { [weak self] weightResult in
            guard let self else { return }

            switch weightResult {
            case .success(let weights):
                HealthKitService.shared.fetchRestingHRSamplesForLast7Days { restingHRResult in
                    switch restingHRResult {
                    case .success(let restingHR):
                        HealthKitService.shared.fetchHRVSamplesForLast7Days { hrvResult in
                            switch hrvResult {
                            case .success(let hrv):
                                HealthKitService.shared.fetchSleepSamplesForLast7Days { sleepResult in
                                    switch sleepResult {
                                    case .success(let sleep):
                                        let sleepNightAggregates = HealthKitService.shared.buildSleepNightAggregates(from: sleep)

                                        self.weightSamples = weights
                                        self.restingHRSamples = restingHR
                                        self.hrvSamples = hrv
                                        self.sleepSamples = sleep
                                        self.sleepNightAggregates = sleepNightAggregates

                                        let payload = HealthKitService.shared.buildHealthSyncPayload(
                                            sleepAggregates: sleepNightAggregates,
                                            restingHRSamples: restingHR,
                                            hrvSamples: hrv,
                                            weightSamples: weights
                                        )
                                        self.updatePayloadSummary(from: payload)
                                        self.statusMessage = "Sample data loaded"
                                        self.refreshStatuses()

                                    case .failure(let error):
                                        self.statusMessage = "Sleep read error: \(error.localizedDescription)"
                                    }
                                }

                            case .failure(let error):
                                self.statusMessage = "HRV read error: \(error.localizedDescription)"
                            }
                        }

                    case .failure(let error):
                        self.statusMessage = "Resting HR read error: \(error.localizedDescription)"
                    }
                }

            case .failure(let error):
                self.statusMessage = "Weight read error: \(error.localizedDescription)"
            }
        }
    }

    func buildPayloadPreview() {
        let payload = HealthKitService.shared.buildHealthSyncPayload(
            sleepAggregates: sleepNightAggregates,
            restingHRSamples: restingHRSamples,
            hrvSamples: hrvSamples,
            weightSamples: weightSamples
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

        do {
            let data = try encoder.encode(payload)
            let fullText = String(data: data, encoding: .utf8) ?? "Failed to render payload"
            let previewLimit = 2200

            if fullText.count > previewLimit {
                payloadPreview = String(fullText.prefix(previewLimit)) + "\n\n... truncated ..."
            } else {
                payloadPreview = fullText
            }

            updatePayloadSummary(from: payload)
            statusMessage = "Payload preview built"
            syncState.lastPayloadGeneratedAt = Date()
            syncState.lastErrorMessage = nil
            syncState.lastSentItemCount = payloadItemCount(payload)
            saveSyncState()

        } catch {
            payloadPreview = ""
            statusMessage = "Payload build error: \(error.localizedDescription)"
            syncState.lastErrorMessage = error.localizedDescription
            saveSyncState()
        }
    }

    // MARK: - Readiness

    func loadTodayReadiness() {
        APIClient.shared.fetchLatestReadiness(userID: backendUserID) { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let response):
                self.todayReadiness = response
                self.readinessErrorMessage = nil

            case .failure(let error):
                self.readinessErrorMessage = error.localizedDescription
            }
        }
    }

    func loadReadinessHistory(days: Int = 7) {
        APIClient.shared.fetchReadinessHistory(
            userID: backendUserID,
            days: days
        ) { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let response):
                self.readinessHistory = response.points

            case .failure:
                self.readinessHistory = []
            }
        }
    }

    // MARK: - Helpers

    func runFullSyncFromMainScreen() {
        performFullSync { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                self.weightSamples = data.weightSamples
                self.restingHRSamples = data.restingHRSamples
                self.hrvSamples = data.hrvSamples
                self.sleepSamples = data.sleepSamples
                self.sleepNightAggregates = data.sleepNightAggregates
                self.updatePayloadSummary(from: data.payload)
                self.refreshStatuses()

                self.sendPayload(data.payload, mode: .full) { [weak self] in
                    self?.isSyncInProgress = false
                }

            case .failure:
                break
            }
        }
    }

    func runIncrementalSyncFromMainScreen() {
        performIncrementalSync { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                guard let payload = data.payload else { return }

                self.newHRVSamples = data.newHRVSamples
                self.newRestingHRSamples = data.newRestingHRSamples
                self.newSleepNightAggregates = data.newSleepNightAggregates
                self.hrvSamples = data.newHRVSamples
                self.restingHRSamples = data.newRestingHRSamples
                self.sleepNightAggregates = data.newSleepNightAggregates
                self.sleepSamples = []
                self.updatePayloadSummary(from: payload)
                self.refreshStatuses()

                self.sendPayload(payload, mode: .incremental) { [weak self] in
                    self?.isSyncInProgress = false
                }

            case .failure:
                break
            }
        }
    }

    func runBackfillSinceMay23FromMainScreen() {
        performBackfill { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                self.weightSamples = data.weightSamples
                self.restingHRSamples = data.restingHRSamples
                self.hrvSamples = data.hrvSamples
                self.sleepSamples = data.sleepSamples
                self.sleepNightAggregates = data.sleepNightAggregates
                self.updatePayloadSummary(from: data.payload)
                self.refreshStatuses()

                self.sendPayload(data.payload, mode: .backfill) { [weak self] in
                    self?.isSyncInProgress = false
                }

            case .failure:
                break
            }
        }
    }

    func payloadItemCount(_ payload: HealthSyncPayload) -> Int {
        payload.sleepNights.count +
        payload.restingHeartRateDaily.count +
        payload.hrvSamples.count +
        (payload.latestWeight == nil ? 0 : 1)
    }

    func updatePayloadSummary(from payload: HealthSyncPayload) {
        let encoder = JSONEncoder()

        do {
            let data = try encoder.encode(payload)
            let itemCount = payloadItemCount(payload)

            if itemCount == 0 {
                payloadSummary = """
                No incremental payload data
                payloadSizeBytes: \(data.count)
                """
                return
            }

            payloadSummary = """
            sleepNights: \(payload.sleepNights.count)
            restingHeartRateDaily: \(payload.restingHeartRateDaily.count)
            hrvSamples: \(payload.hrvSamples.count)
            latestWeight: \(payload.latestWeight == nil ? 0 : 1)
            payloadSizeBytes: \(data.count)
            """
        } catch {
            payloadSummary = "Failed to build payload summary"
        }
    }

    var latestWeightValue: String {
        guard let weight = weightSamples.sorted(by: { $0.date > $1.date }).first else {
            return "N/A"
        }

        return String(format: "%.1f kg", weight.kilograms)
    }

    var lastSyncDisplayText: String {
        if let lastSuccessfulSyncAt = syncState.lastSuccessfulSyncAt {
            return DateFormatters.shortDateTime(lastSuccessfulSyncAt)
        }

        return "NONE"
    }

    var lastPayloadDisplayText: String {
        if let lastPayloadGeneratedAt = syncState.lastPayloadGeneratedAt {
            return DateFormatters.shortDateTime(lastPayloadGeneratedAt)
        }

        return "NONE"
    }

    var lastSyncModeDisplayText: String {
        syncState.lastSyncMode?.rawValue.uppercased() ?? "NONE"
    }

    var backendDisplayName: String {
        APIClient.shared.configuredBaseURLDisplayString.uppercased()
    }

    var backendStatusLabel: String {
        if syncState.lastErrorMessage == nil, syncState.lastSuccessfulSyncAt != nil {
            return "CONNECTED"
        }

        return "CONFIGURED"
    }

    var backendStatusColor: String {
        if syncState.lastErrorMessage == nil, syncState.lastSuccessfulSyncAt != nil {
            return "connected"
        }

        return "configured"
    }

    var healthKitStatusLabel: String {
        let readOKCount = authorizationItems.filter { $0.status == "READ OK" }.count

        if readOKCount == authorizationItems.count, !authorizationItems.isEmpty {
            return "READ OK"
        }

        if !hasRequestedHealthPermissions {
            return "NOT REQUESTED"
        }

        return "NO DATA"
    }

    var healthKitStatusColor: String {
        switch healthKitStatusLabel {
        case "READ OK":
            return "connected"
        case "NOT REQUESTED":
            return "configured"
        case "NO DATA":
            return "warning"
        default:
            return "configured"
        }
    }

    private func payloadItemCount(from data: IncrementalSyncData) -> Int {
        guard let payload = data.payload else { return 0 }
        return payloadItemCount(payload)
    }

    private func syncSuccessTitle(for mode: SyncMode) -> String {
        switch mode {
        case .full:
            return "Full sync sent"
        case .incremental:
            return "Incremental sent"
        case .backfill:
            return "Backfill sent"
        }
    }

    private func readStatus(hasData: Bool) -> String {
        if !hasRequestedHealthPermissions {
            return "NOT REQUESTED"
        }

        return hasData ? "READ OK" : "NO DATA / CHECK HEALTH SETTINGS"
    }
}
