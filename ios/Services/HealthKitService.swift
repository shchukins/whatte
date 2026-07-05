//
//  HealthKitService.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 05.04.2026.
//

import Foundation
import HealthKit


final class HealthKitService {
    static let shared = HealthKitService()
    private static let hasRequestedPermissionsKey = "healthkit_read_permissions_requested"

    private let healthStore = HKHealthStore()

    private init() {}

    var isHealthDataAvailable: Bool {
        HKHealthStore.isHealthDataAvailable()
    }

    var hasRequestedAuthorization: Bool {
        UserDefaults.standard.bool(forKey: Self.hasRequestedPermissionsKey)
    }

    func fetchSleepSamplesForLast7Days(completion: @escaping (Result<[SleepSample], Error>) -> Void) {
        let startDate = Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date.distantPast
        fetchSleepSamples(from: startDate, completion: completion)
    }

    func fetchSleepSamples(from startDate: Date, completion: @escaping (Result<[SleepSample], Error>) -> Void) {
        guard let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let predicate = samplesPredicate(from: startDate)
        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: sleepType,
            predicate: predicate,
            limit: HKObjectQueryNoLimit,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKCategorySample] ?? []).map { sample in
                    SleepSample(
                        startDate: sample.startDate,
                        endDate: sample.endDate,
                        durationMinutes: sample.endDate.timeIntervalSince(sample.startDate) / 60.0,
                        stage: Self.mapSleepStage(sample.value)
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    
    func requestAuthorization(completion: @escaping (Result<Void, Error>) -> Void) {
        UserDefaults.standard.set(true, forKey: Self.hasRequestedPermissionsKey)

        guard isHealthDataAvailable else {
            completion(.failure(HealthKitError.notAvailable))
            return
        }

        guard
            let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis),
            let hrvType = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN),
            let restingHeartRateType = HKObjectType.quantityType(forIdentifier: .restingHeartRate),
            let bodyMassType = HKObjectType.quantityType(forIdentifier: .bodyMass)
        else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let readTypes: Set<HKObjectType> = [
            sleepType,
            hrvType,
            restingHeartRateType,
            bodyMassType
        ]

        healthStore.requestAuthorization(toShare: nil, read: readTypes) { success, error in
            DispatchQueue.main.async {
                if let error = error {
                    completion(.failure(error))
                    return
                }

                if success {
                    completion(.success(()))
                } else {
                    completion(.failure(HealthKitError.authorizationFailed))
                }
            }
        }
    }

    func authorizationStatuses() -> [String: HKAuthorizationStatus] {
        var result: [String: HKAuthorizationStatus] = [:]

        if let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            result["Sleep"] = healthStore.authorizationStatus(for: sleepType)
        }

        if let hrvType = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN) {
            result["HRV"] = healthStore.authorizationStatus(for: hrvType)
        }

        if let restingHeartRateType = HKObjectType.quantityType(forIdentifier: .restingHeartRate) {
            result["Resting HR"] = healthStore.authorizationStatus(for: restingHeartRateType)
        }

        if let bodyMassType = HKObjectType.quantityType(forIdentifier: .bodyMass) {
            result["Weight"] = healthStore.authorizationStatus(for: bodyMassType)
        }

        return result
    }

    func fetchLatestWeightSample(completion: @escaping (Result<[WeightSample], Error>) -> Void) {
        guard let bodyMassType = HKObjectType.quantityType(forIdentifier: .bodyMass) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let startDate = Calendar.current.date(byAdding: .day, value: -365, to: Date()) ?? Date.distantPast
        let predicate = HKQuery.predicateForSamples(
            withStart: startDate,
            end: Date(),
            options: .strictStartDate
        )

        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: bodyMassType,
            predicate: predicate,
            limit: 1,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    WeightSample(
                        date: sample.startDate,
                        kilograms: sample.quantity.doubleValue(for: .gramUnit(with: .kilo))
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    func fetchWeightSamplesForLast7Days(completion: @escaping (Result<[WeightSample], Error>) -> Void) {
        guard let bodyMassType = HKObjectType.quantityType(forIdentifier: .bodyMass) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let startDate = Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date.distantPast
        let predicate = samplesPredicate(from: startDate)
        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: bodyMassType,
            predicate: predicate,
            limit: 20,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    WeightSample(
                        date: sample.startDate,
                        kilograms: sample.quantity.doubleValue(for: .gramUnit(with: .kilo))
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }

    func fetchRestingHRSamplesForLast7Days(completion: @escaping (Result<[RestingHRSample], Error>) -> Void) {
        let startDate = Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date.distantPast
        fetchRestingHRSamples(from: startDate, completion: completion)
    }

    func fetchRestingHRSamples(from startDate: Date, completion: @escaping (Result<[RestingHRSample], Error>) -> Void) {
        guard let restingHeartRateType = HKObjectType.quantityType(forIdentifier: .restingHeartRate) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let predicate = samplesPredicate(from: startDate)
        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: restingHeartRateType,
            predicate: predicate,
            limit: HKObjectQueryNoLimit,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let unit = HKUnit.count().unitDivided(by: .minute())
                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    RestingHRSample(
                        date: sample.startDate,
                        bpm: sample.quantity.doubleValue(for: unit)
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }

    func fetchHRVSamplesForLast7Days(completion: @escaping (Result<[HRVSample], Error>) -> Void) {
        let startDate = Calendar.current.date(byAdding: .day, value: -7, to: Date()) ?? Date.distantPast
        fetchHRVSamples(from: startDate, completion: completion)
    }

    func fetchHRVSamples(from startDate: Date, completion: @escaping (Result<[HRVSample], Error>) -> Void) {
        guard let hrvType = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let predicate = samplesPredicate(from: startDate)
        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: hrvType,
            predicate: predicate,
            limit: HKObjectQueryNoLimit,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    HRVSample(
                        date: sample.startDate,
                        milliseconds: sample.quantity.doubleValue(for: .secondUnit(with: .milli))
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }

    func buildSleepNightAggregates(from samples: [SleepSample]) -> [SleepNightAggregate] {
        let grouped = Dictionary(grouping: samples) { sample in
            Calendar.current.startOfDay(for: sample.endDate)
        }

        let aggregates = grouped.compactMap { wakeDate, nightSamples -> SleepNightAggregate? in
            guard !nightSamples.isEmpty else { return nil }

            let sorted = nightSamples.sorted { $0.startDate < $1.startDate }

            let sleepStart = sorted.first?.startDate ?? wakeDate
            let sleepEnd = sorted.last?.endDate ?? wakeDate

            var totalSleepMinutes: Double = 0
            var awakeMinutes: Double = 0
            var coreMinutes: Double = 0
            var remMinutes: Double = 0
            var deepMinutes: Double = 0
            var inBedMinutes: Double = 0

            for sample in nightSamples {
                switch sample.stage {
                case "Asleep":
                    totalSleepMinutes += sample.durationMinutes
                case "Core":
                    coreMinutes += sample.durationMinutes
                    totalSleepMinutes += sample.durationMinutes
                case "REM":
                    remMinutes += sample.durationMinutes
                    totalSleepMinutes += sample.durationMinutes
                case "Deep":
                    deepMinutes += sample.durationMinutes
                    totalSleepMinutes += sample.durationMinutes
                case "Awake":
                    awakeMinutes += sample.durationMinutes
                case "In Bed":
                    inBedMinutes += sample.durationMinutes
                default:
                    break
                }
            }

            return SleepNightAggregate(
                wakeDate: wakeDate,
                sleepStart: sleepStart,
                sleepEnd: sleepEnd,
                totalSleepMinutes: totalSleepMinutes,
                awakeMinutes: awakeMinutes,
                coreMinutes: coreMinutes,
                remMinutes: remMinutes,
                deepMinutes: deepMinutes,
                inBedMinutes: inBedMinutes
            )
        }

        return aggregates.sorted { $0.wakeDate > $1.wakeDate }
    }
    
    func fetchHRVIncremental(
        completion: @escaping (Result<[HRVSample], Error>) -> Void
    ) {
        guard let hrvType = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let anchor = HealthKitAnchorStore.shared.loadAnchor(for: "hrv")

        let query = HKAnchoredObjectQuery(
            type: hrvType,
            predicate: nil,
            anchor: anchor,
            limit: HKObjectQueryNoLimit
        ) { _, samples, _, newAnchor, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    HRVSample(
                        date: sample.startDate,
                        milliseconds: sample.quantity.doubleValue(for: .secondUnit(with: .milli))
                    )
                }

                if let newAnchor {
                    HealthKitAnchorStore.shared.saveAnchor(newAnchor, for: "hrv")
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    func fetchRestingHRIncremental(
        completion: @escaping (Result<[RestingHRSample], Error>) -> Void
    ) {
        guard let restingHeartRateType = HKObjectType.quantityType(forIdentifier: .restingHeartRate) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let anchor = HealthKitAnchorStore.shared.loadAnchor(for: "resting_hr")

        let query = HKAnchoredObjectQuery(
            type: restingHeartRateType,
            predicate: nil,
            anchor: anchor,
            limit: HKObjectQueryNoLimit
        ) { _, samples, _, newAnchor, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let unit = HKUnit.count().unitDivided(by: .minute())
                let result = (samples as? [HKQuantitySample] ?? []).map { sample in
                    RestingHRSample(
                        date: sample.startDate,
                        bpm: sample.quantity.doubleValue(for: unit)
                    )
                }

                if let newAnchor {
                    HealthKitAnchorStore.shared.saveAnchor(newAnchor, for: "resting_hr")
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    func fetchSleepIncremental(
        completion: @escaping (Result<[SleepSample], Error>) -> Void
    ) {
        guard let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let anchor = HealthKitAnchorStore.shared.loadAnchor(for: "sleep")

        let query = HKAnchoredObjectQuery(
            type: sleepType,
            predicate: nil,
            anchor: anchor,
            limit: HKObjectQueryNoLimit
        ) { _, samples, _, newAnchor, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKCategorySample] ?? []).map { sample in
                    SleepSample(
                        startDate: sample.startDate,
                        endDate: sample.endDate,
                        durationMinutes: sample.endDate.timeIntervalSince(sample.startDate) / 60.0,
                        stage: Self.mapSleepStage(sample.value)
                    )
                }

                if let newAnchor {
                    HealthKitAnchorStore.shared.saveAnchor(newAnchor, for: "sleep")
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    private func samplesPredicate(from startDate: Date) -> NSPredicate {
        return HKQuery.predicateForSamples(
            withStart: startDate,
            end: Date(),
            options: .strictStartDate
        )
    }
    
    private static func mapSleepStage(_ value: Int) -> String {
        if #available(iOS 16.0, *) {
            switch value {
            case HKCategoryValueSleepAnalysis.inBed.rawValue:
                return "In Bed"
            case HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue:
                return "Asleep"
            case HKCategoryValueSleepAnalysis.awake.rawValue:
                return "Awake"
            case HKCategoryValueSleepAnalysis.asleepCore.rawValue:
                return "Core"
            case HKCategoryValueSleepAnalysis.asleepDeep.rawValue:
                return "Deep"
            case HKCategoryValueSleepAnalysis.asleepREM.rawValue:
                return "REM"
            default:
                return "Other"
            }
        } else {
            switch value {
            case HKCategoryValueSleepAnalysis.inBed.rawValue:
                return "In Bed"
            case HKCategoryValueSleepAnalysis.asleep.rawValue:
                return "Asleep"
            case HKCategoryValueSleepAnalysis.awake.rawValue:
                return "Awake"
            default:
                return "Other"
            }
        }
    }
    
    func buildSleepNightDTOs(from aggregates: [SleepNightAggregate]) -> [SleepNightDTO] {
        aggregates.map { night in
            SleepNightDTO(
                wakeDate: isoDateString(from: night.wakeDate),
                sleepStart: isoDateTimeString(from: night.sleepStart),
                sleepEnd: isoDateTimeString(from: night.sleepEnd),
                totalSleepMinutes: night.totalSleepMinutes,
                awakeMinutes: night.awakeMinutes,
                coreMinutes: night.coreMinutes,
                remMinutes: night.remMinutes,
                deepMinutes: night.deepMinutes,
                inBedMinutes: night.inBedMinutes > 0 ? night.inBedMinutes : nil
            )
        }
    }

    func buildRestingHRDailyDTOs(from samples: [RestingHRSample]) -> [RestingHRDailyDTO] {
        let grouped = Dictionary(grouping: samples) { sample in
            Calendar.current.startOfDay(for: sample.date)
        }

        let daily = grouped.compactMap { date, daySamples -> RestingHRDailyDTO? in
            guard let latest = daySamples.sorted(by: { $0.date > $1.date }).first else {
                return nil
            }

            return RestingHRDailyDTO(
                date: isoDateString(from: date),
                bpm: latest.bpm
            )
        }

        return daily.sorted { $0.date > $1.date }
    }

    func buildHRVSampleDTOs(from samples: [HRVSample]) -> [HRVSampleDTO] {
        samples.map { sample in
            HRVSampleDTO(
                startAt: isoDateTimeString(from: sample.date),
                valueMs: sample.milliseconds
            )
        }
    }

    func buildLatestWeightDTO(from samples: [WeightSample]) -> LatestWeightDTO? {
        guard let latest = samples.sorted(by: { $0.date > $1.date }).first else {
            return nil
        }

        return LatestWeightDTO(
            measuredAt: isoDateTimeString(from: latest.date),
            kilograms: latest.kilograms
        )
    }

    func buildHealthSyncPayload(
        sleepAggregates: [SleepNightAggregate],
        restingHRSamples: [RestingHRSample],
        hrvSamples: [HRVSample],
        weightSamples: [WeightSample]
    ) -> HealthSyncPayload {
        HealthSyncPayload(
            generatedAt: isoDateTimeString(from: Date()),
            timezone: TimeZone.current.identifier,
            sleepNights: buildSleepNightDTOs(from: sleepAggregates),
            restingHeartRateDaily: buildRestingHRDailyDTOs(from: restingHRSamples),
            hrvSamples: buildHRVSampleDTOs(from: hrvSamples),
            latestWeight: buildLatestWeightDTO(from: weightSamples)
        )
    }

    private func isoDateString(from date: Date) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .iso8601)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    private func isoDateTimeString(from date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
    
    func affectedWakeDates(from sleepSamples: [SleepSample]) -> [Date] {
        let dates = sleepSamples.map { sample in
            Calendar.current.startOfDay(for: sample.endDate)
        }

        let uniqueDates = Array(Set(dates))
        return uniqueDates.sorted(by: >)
    }
    
    func fetchSleepSamples(forWakeDate wakeDate: Date, completion: @escaping (Result<[SleepSample], Error>) -> Void) {
        guard let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
            completion(.failure(HealthKitError.typeNotAvailable))
            return
        }

        let calendar = Calendar.current

        guard
            let windowStart = calendar.date(byAdding: .day, value: -1, to: wakeDate),
            let start = calendar.date(bySettingHour: 12, minute: 0, second: 0, of: windowStart),
            let end = calendar.date(bySettingHour: 14, minute: 0, second: 0, of: wakeDate)
        else {
            completion(.failure(HealthKitError.invalidDateRange))
            return
        }

        let predicate = HKQuery.predicateForSamples(
            withStart: start,
            end: end,
            options: .strictStartDate
        )

        let sortDescriptors = [
            NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)
        ]

        let query = HKSampleQuery(
            sampleType: sleepType,
            predicate: predicate,
            limit: HKObjectQueryNoLimit,
            sortDescriptors: sortDescriptors
        ) { _, samples, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error))
                    return
                }

                let result = (samples as? [HKCategorySample] ?? []).map { sample in
                    SleepSample(
                        startDate: sample.startDate,
                        endDate: sample.endDate,
                        durationMinutes: sample.endDate.timeIntervalSince(sample.startDate) / 60.0,
                        stage: Self.mapSleepStage(sample.value)
                    )
                }

                completion(.success(result))
            }
        }

        healthStore.execute(query)
    }
    
    func enableObservers() {
        observeHRV()
        observeRestingHR()
        observeSleep()
    }
    
    private func observeHRV() {
        guard let type = HKObjectType.quantityType(forIdentifier: .heartRateVariabilitySDNN) else {
            return
        }

        let query = HKObserverQuery(sampleType: type, predicate: nil) { _, completionHandler, error in
            if let error {
                print("HRV observer error: \(error.localizedDescription)")
                completionHandler()
                return
            }

            DispatchQueue.main.async {
                NotificationCenter.default.post(name: .healthKitHRVUpdated, object: nil)
            }

            completionHandler()
        }

        healthStore.execute(query)
        healthStore.enableBackgroundDelivery(for: type, frequency: .immediate) { _, _ in }
    }
    
    private func observeRestingHR() {
        guard let type = HKObjectType.quantityType(forIdentifier: .restingHeartRate) else {
            return
        }

        let query = HKObserverQuery(sampleType: type, predicate: nil) { _, completionHandler, error in
            if let error {
                print("Resting HR observer error: \(error.localizedDescription)")
                completionHandler()
                return
            }

            DispatchQueue.main.async {
                NotificationCenter.default.post(name: .healthKitRestingHRUpdated, object: nil)
            }

            completionHandler()
        }

        healthStore.execute(query)
        healthStore.enableBackgroundDelivery(for: type, frequency: .immediate) { _, _ in }
    }
    
    private func observeSleep() {
        guard let type = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
            return
        }

        let query = HKObserverQuery(sampleType: type, predicate: nil) { _, completionHandler, error in
            if let error {
                print("Sleep observer error: \(error.localizedDescription)")
                completionHandler()
                return
            }

            DispatchQueue.main.async {
                NotificationCenter.default.post(name: .healthKitSleepUpdated, object: nil)
            }

            completionHandler()
        }

        healthStore.execute(query)
        healthStore.enableBackgroundDelivery(for: type, frequency: .immediate) { _, _ in }
    }
}

enum HealthKitError: LocalizedError {
    case notAvailable
    case typeNotAvailable
    case authorizationFailed
    case invalidDateRange

    var errorDescription: String? {
        switch self {
        case .notAvailable:
            return "Health data is not available on this device."
        case .typeNotAvailable:
            return "Required HealthKit data types are not available."
        case .authorizationFailed:
            return "HealthKit authorization was not granted."
        case .invalidDateRange:
            return "Invalid date range"
        }
    }
}
