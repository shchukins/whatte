//
//  SyncService.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

struct FullSyncData {
    let weightSamples: [WeightSample]
    let restingHRSamples: [RestingHRSample]
    let hrvSamples: [HRVSample]
    let sleepSamples: [SleepSample]
    let sleepNightAggregates: [SleepNightAggregate]
    let payload: HealthSyncPayload
}

struct IncrementalSyncData {
    let newHRVSamples: [HRVSample]
    let newRestingHRSamples: [RestingHRSample]
    let newSleepNightAggregates: [SleepNightAggregate]
    let payload: HealthSyncPayload?
}

final class SyncService {
    static let shared = SyncService()

    private init() {}

    func performFullSync(completion: @escaping (Result<FullSyncData, Error>) -> Void) {
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

                                        let payload = HealthKitService.shared.buildHealthSyncPayload(
                                            sleepAggregates: sleepNightAggregates,
                                            restingHRSamples: restingHR,
                                            hrvSamples: hrv,
                                            weightSamples: weights
                                        )

                                        let result = FullSyncData(
                                            weightSamples: weights,
                                            restingHRSamples: restingHR,
                                            hrvSamples: hrv,
                                            sleepSamples: sleep,
                                            sleepNightAggregates: sleepNightAggregates,
                                            payload: payload
                                        )

                                        completion(.success(result))

                                    case .failure(let error):
                                        completion(.failure(error))
                                    }
                                }

                            case .failure(let error):
                                completion(.failure(error))
                            }
                        }

                    case .failure(let error):
                        completion(.failure(error))
                    }
                }

            case .failure(let error):
                completion(.failure(error))
            }
        }
    }

    // TODO: Remove this temporary migration backfill path after historical HealthKit recovery is no longer needed.
    func performBackfill(
        from startDate: Date,
        completion: @escaping (Result<FullSyncData, Error>) -> Void
    ) {
        HealthKitService.shared.fetchLatestWeightSample { weightResult in
            switch weightResult {
            case .success(let weights):
                HealthKitService.shared.fetchRestingHRSamples(from: startDate) { restingHRResult in
                    switch restingHRResult {
                    case .success(let restingHR):
                        HealthKitService.shared.fetchHRVSamples(from: startDate) { hrvResult in
                            switch hrvResult {
                            case .success(let hrv):
                                HealthKitService.shared.fetchSleepSamples(from: startDate) { sleepResult in
                                    switch sleepResult {
                                    case .success(let sleep):
                                        let sleepNightAggregates = HealthKitService.shared.buildSleepNightAggregates(from: sleep)

                                        let payload = HealthKitService.shared.buildHealthSyncPayload(
                                            sleepAggregates: sleepNightAggregates,
                                            restingHRSamples: restingHR,
                                            hrvSamples: hrv,
                                            weightSamples: weights
                                        )

                                        let result = FullSyncData(
                                            weightSamples: weights,
                                            restingHRSamples: restingHR,
                                            hrvSamples: hrv,
                                            sleepSamples: sleep,
                                            sleepNightAggregates: sleepNightAggregates,
                                            payload: payload
                                        )

                                        completion(.success(result))

                                    case .failure(let error):
                                        completion(.failure(error))
                                    }
                                }

                            case .failure(let error):
                                completion(.failure(error))
                            }
                        }

                    case .failure(let error):
                        completion(.failure(error))
                    }
                }

            case .failure(let error):
                completion(.failure(error))
            }
        }
    }

    func performIncrementalSync(completion: @escaping (Result<IncrementalSyncData, Error>) -> Void) {
        HealthKitService.shared.fetchHRVIncremental { hrvResult in
            switch hrvResult {
            case .success(let newHRV):
                HealthKitService.shared.fetchRestingHRIncremental { restingHRResult in
                    switch restingHRResult {
                    case .success(let newRestingHR):
                        HealthKitService.shared.fetchSleepIncremental { sleepResult in
                            switch sleepResult {
                            case .success(let changedSleepSegments):
                                let affectedWakeDates = HealthKitService.shared.affectedWakeDates(from: changedSleepSegments)

                                self.rebuildAffectedSleepNights(wakeDates: affectedWakeDates) { rebuiltSleepNights in
                                    let hasNoChanges = newHRV.isEmpty && newRestingHR.isEmpty && rebuiltSleepNights.isEmpty

                                    if hasNoChanges {
                                        let result = IncrementalSyncData(
                                            newHRVSamples: [],
                                            newRestingHRSamples: [],
                                            newSleepNightAggregates: [],
                                            payload: nil
                                        )
                                        completion(.success(result))
                                        return
                                    }

                                    let payload = HealthSyncPayload(
                                        generatedAt: ISO8601DateFormatter().string(from: Date()),
                                        timezone: TimeZone.current.identifier,
                                        sleepNights: HealthKitService.shared.buildSleepNightDTOs(from: rebuiltSleepNights),
                                        restingHeartRateDaily: HealthKitService.shared.buildRestingHRDailyDTOs(from: newRestingHR),
                                        hrvSamples: HealthKitService.shared.buildHRVSampleDTOs(from: newHRV),
                                        latestWeight: nil
                                    )

                                    let result = IncrementalSyncData(
                                        newHRVSamples: newHRV,
                                        newRestingHRSamples: newRestingHR,
                                        newSleepNightAggregates: rebuiltSleepNights,
                                        payload: payload
                                    )

                                    completion(.success(result))
                                }

                            case .failure(let error):
                                completion(.failure(error))
                            }
                        }

                    case .failure(let error):
                        completion(.failure(error))
                    }
                }

            case .failure(let error):
                completion(.failure(error))
            }
        }
    }

    func sendPayload(
        _ payload: HealthSyncPayload,
        userID: String,
        completion: @escaping (Result<HealthIngestAndProcessResponse, Error>) -> Void
    ) {
        APIClient.shared.sendHealthPayload(
            payload,
            userID: userID,
            completion: completion
        )
    }

    private func rebuildAffectedSleepNights(
        wakeDates: [Date],
        completion: @escaping ([SleepNightAggregate]) -> Void
    ) {
        guard !wakeDates.isEmpty else {
            completion([])
            return
        }

        var rebuilt: [SleepNightAggregate] = []
        var remaining = wakeDates

        func processNext() {
            guard let wakeDate = remaining.first else {
                completion(rebuilt.sorted { $0.wakeDate > $1.wakeDate })
                return
            }

            remaining.removeFirst()

            HealthKitService.shared.fetchSleepSamples(forWakeDate: wakeDate) { result in
                switch result {
                case .success(let samples):
                    let aggregates = HealthKitService.shared.buildSleepNightAggregates(from: samples)

                    if let matching = aggregates.first(where: {
                        Calendar.current.isDate($0.wakeDate, inSameDayAs: wakeDate)
                    }) {
                        rebuilt.append(matching)
                    }

                    processNext()

                case .failure:
                    processNext()
                }
            }
        }

        processNext()
    }
}
