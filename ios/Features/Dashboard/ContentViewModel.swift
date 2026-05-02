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

    // MARK: - Loaded HealthKit data used by sync pipeline

    var weightSamples: [WeightSample] = []
    var restingHRSamples: [RestingHRSample] = []
    var hrvSamples: [HRVSample] = []
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
    var syncState: SyncState = SyncStateStore.shared.load()
    var isSyncInProgress: Bool = false

    let backendUserID: String = "sergey"

    // MARK: - Startup logic

    private var hasPerformedInitialSync = false

    // MARK: - Sync state

    func reloadSyncState() {
        syncState = SyncStateStore.shared.load()
    }

    func saveSyncState() {
        SyncStateStore.shared.save(syncState)
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
                \(mode == .full ? "Full sync sent" : "Incremental sent")
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

    // MARK: - Readiness

    func loadTodayReadiness() {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let today = formatter.string(from: Date())

        APIClient.shared.fetchReadiness(
            userID: backendUserID,
            date: today
        ) { [weak self] result in
            guard let self else { return }

            switch result {
            case .success(let response):
                self.todayReadiness = response
                self.readinessErrorMessage = nil

            case .failure(let error):
                self.todayReadiness = nil
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

    func payloadItemCount(_ payload: HealthSyncPayload) -> Int {
        payload.sleepNights.count +
        payload.restingHeartRateDaily.count +
        payload.hrvSamples.count +
        (payload.latestWeight == nil ? 0 : 1)
    }

    private func payloadItemCount(from data: IncrementalSyncData) -> Int {
        guard let payload = data.payload else { return 0 }
        return payloadItemCount(payload)
    }
}
