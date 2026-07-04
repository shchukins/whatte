import Foundation
import Observation

@Observable
final class DebugViewModel {
    private static let backfillStartDate: Date = {
        let calendar = Calendar(identifier: .gregorian)
        return calendar.date(from: DateComponents(year: 2026, month: 5, day: 23)) ?? Date.distantPast
    }()
    private static let hasRequestedPermissionsKey = "healthkit_read_permissions_requested"

    // MARK: - Loaded HealthKit data

    var weightSamples: [WeightSample] = []
    var restingHRSamples: [RestingHRSample] = []
    var hrvSamples: [HRVSample] = []
    var sleepSamples: [SleepSample] = []
    var sleepNightAggregates: [SleepNightAggregate] = []

    // MARK: - UI state

    var statusMessage: String = "Not requested"
    var authorizationItems: [(name: String, status: String)] = []
    var payloadPreview: String = ""
    var payloadSummary: String = ""
    var syncState: SyncState = SyncStateStore.shared.load()
    var isSyncInProgress: Bool = false

    let backendUserID: String = "sergey"
    private var hasRequestedHealthPermissions = UserDefaults.standard.bool(forKey: hasRequestedPermissionsKey)

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

    // MARK: - Sync state

    func reloadSyncState() {
        syncState = SyncStateStore.shared.load()
    }

    func resetSyncState() {
        syncState = .empty
        SyncStateStore.shared.clear()
        statusMessage = "Sync state reset"
        refreshStatuses()
    }

    func saveSyncState() {
        SyncStateStore.shared.save(syncState)
    }

    // MARK: - Read sample data

    func readSampleData() {
        statusMessage = "Reading sample data..."

        HealthKitService.shared.fetchLatestWeightSample { weightResult in
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

    // MARK: - Payload preview

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

            let previewLimit = 4000
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

    func payloadItemCount(_ payload: HealthSyncPayload) -> Int {
        payload.sleepNights.count +
        payload.restingHeartRateDaily.count +
        payload.hrvSamples.count +
        (payload.latestWeight == nil ? 0 : 1)
    }

    private func syncSuccessMessage(for mode: SyncMode) -> String {
        switch mode {
        case .full:
            return "Full sync sent"
        case .incremental:
            return "Incremental sent"
        case .backfill:
            return "Backfill sent"
        }
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
            case .success:
                self.statusMessage = self.syncSuccessMessage(for: mode)
                self.syncState.lastSuccessfulSyncAt = Date()
                self.syncState.lastPayloadGeneratedAt = Date()
                self.syncState.lastErrorMessage = nil
                self.syncState.lastSentItemCount = itemCount
                self.syncState.lastSyncMode = mode
                self.saveSyncState()

            case .failure(let error):
                self.statusMessage = "Send error: \(error.localizedDescription)"
                self.syncState.lastPayloadGeneratedAt = Date()
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
            }

            self.isSyncInProgress = false
            completion()
        }
    }

    // MARK: - Backfill

    func performBackfillSinceMay23() {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running backfill since 2026-05-23..."

        SyncService.shared.performBackfill(from: Self.backfillStartDate) { [weak self] result in
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

                self.sendPayload(data.payload, mode: .backfill) {}

            case .failure(let error):
                self.statusMessage = "Backfill error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
            }
        }
    }

    // MARK: - Full sync

    func performFullSync() {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running full sync..."

        SyncService.shared.performFullSync { [weak self] result in
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

                self.sendPayload(data.payload, mode: .full) {}

            case .failure(let error):
                self.statusMessage = "Full sync error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
            }
        }
    }

    // MARK: - Incremental sync

    func performIncrementalSync() {
        guard !isSyncInProgress else { return }

        isSyncInProgress = true
        statusMessage = "Running incremental sync..."

        SyncService.shared.performIncrementalSync { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let data):
                guard let payload = data.payload else {
                    self.statusMessage = "Incremental sync: no new data"
                    self.syncState.lastErrorMessage = nil
                    self.syncState.lastSyncMode = .incremental
                    self.saveSyncState()
                    self.isSyncInProgress = false
                    return
                }

                self.hrvSamples = data.newHRVSamples
                self.restingHRSamples = data.newRestingHRSamples
                self.sleepSamples = []
                self.sleepNightAggregates = data.newSleepNightAggregates
                self.updatePayloadSummary(from: payload)
                self.refreshStatuses()

                self.sendPayload(payload, mode: .incremental) {}

            case .failure(let error):
                self.statusMessage = "Incremental sync error: \(error.localizedDescription)"
                self.syncState.lastErrorMessage = error.localizedDescription
                self.saveSyncState()
                self.isSyncInProgress = false
            }
        }
    }

    private func readStatus(hasData: Bool) -> String {
        if !hasRequestedHealthPermissions {
            return "NOT REQUESTED"
        }

        return hasData ? "READ OK" : "NO DATA / CHECK HEALTH SETTINGS"
    }
}
