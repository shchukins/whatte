//
//  HealthSamples.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

// MARK: - Raw / near-raw HealthKit samples used inside the iOS app

struct WeightSample: Identifiable {
    let id = UUID()
    let date: Date
    let kilograms: Double
}

struct RestingHRSample: Identifiable {
    let id = UUID()
    let date: Date
    let bpm: Double
}

struct HRVSample: Identifiable {
    let id = UUID()
    let date: Date
    let milliseconds: Double
}

struct SleepSample: Identifiable {
    let id = UUID()
    let startDate: Date
    let endDate: Date
    let durationMinutes: Double
    let stage: String
}

// MARK: - Aggregated sleep model used for payload building and UI

struct SleepNightAggregate: Identifiable {
    let id = UUID()
    let wakeDate: Date
    let sleepStart: Date
    let sleepEnd: Date

    let totalSleepMinutes: Double
    let awakeMinutes: Double
    let coreMinutes: Double
    let remMinutes: Double
    let deepMinutes: Double
    let inBedMinutes: Double
}

struct LatestHealthSnapshot: Codable {
    struct SleepNight: Codable {
        let wakeDate: Date
        let sleepStart: Date
        let sleepEnd: Date
        let totalSleepMinutes: Double
        let awakeMinutes: Double
        let coreMinutes: Double
        let remMinutes: Double
        let deepMinutes: Double
        let inBedMinutes: Double
    }

    struct HRVValue: Codable {
        let date: Date
        let milliseconds: Double
    }

    struct RestingHRValue: Codable {
        let date: Date
        let bpm: Double
    }

    struct WeightValue: Codable {
        let date: Date
        let kilograms: Double
    }

    let latestSleepNight: SleepNight?
    let latestHRV: HRVValue?
    let latestRestingHR: RestingHRValue?
    let latestWeight: WeightValue?
    let updatedAt: Date
}

extension LatestHealthSnapshot {
    init(
        sleepNightAggregates: [SleepNightAggregate],
        hrvSamples: [HRVSample],
        restingHRSamples: [RestingHRSample],
        weightSamples: [WeightSample],
        updatedAt: Date = Date()
    ) {
        self.latestSleepNight = sleepNightAggregates
            .max(by: { $0.wakeDate < $1.wakeDate })
            .map { Self.makeSleepNight(from: $0) }
        self.latestHRV = hrvSamples
            .max(by: { $0.date < $1.date })
            .map { Self.makeHRVValue(from: $0) }
        self.latestRestingHR = restingHRSamples
            .max(by: { $0.date < $1.date })
            .map { Self.makeRestingHRValue(from: $0) }
        self.latestWeight = weightSamples
            .max(by: { $0.date < $1.date })
            .map { Self.makeWeightValue(from: $0) }
        self.updatedAt = updatedAt
    }

    func merged(
        sleepNightAggregates: [SleepNightAggregate] = [],
        hrvSamples: [HRVSample] = [],
        restingHRSamples: [RestingHRSample] = [],
        weightSamples: [WeightSample] = [],
        updatedAt: Date = Date()
    ) -> LatestHealthSnapshot {
        LatestHealthSnapshot(
            latestSleepNight: Self.mergeSleepNight(
                current: latestSleepNight,
                candidate: sleepNightAggregates.max(by: { $0.wakeDate < $1.wakeDate }).map { Self.makeSleepNight(from: $0) }
            ),
            latestHRV: Self.mergeHRV(
                current: latestHRV,
                candidate: hrvSamples.max(by: { $0.date < $1.date }).map { Self.makeHRVValue(from: $0) }
            ),
            latestRestingHR: Self.mergeRestingHR(
                current: latestRestingHR,
                candidate: restingHRSamples.max(by: { $0.date < $1.date }).map { Self.makeRestingHRValue(from: $0) }
            ),
            latestWeight: Self.mergeWeight(
                current: latestWeight,
                candidate: weightSamples.max(by: { $0.date < $1.date }).map { Self.makeWeightValue(from: $0) }
            ),
            updatedAt: updatedAt
        )
    }

    var sleepNightAggregate: SleepNightAggregate? {
        guard let latestSleepNight else { return nil }
        return SleepNightAggregate(
            wakeDate: latestSleepNight.wakeDate,
            sleepStart: latestSleepNight.sleepStart,
            sleepEnd: latestSleepNight.sleepEnd,
            totalSleepMinutes: latestSleepNight.totalSleepMinutes,
            awakeMinutes: latestSleepNight.awakeMinutes,
            coreMinutes: latestSleepNight.coreMinutes,
            remMinutes: latestSleepNight.remMinutes,
            deepMinutes: latestSleepNight.deepMinutes,
            inBedMinutes: latestSleepNight.inBedMinutes
        )
    }

    var hrvSample: HRVSample? {
        guard let latestHRV else { return nil }
        return HRVSample(date: latestHRV.date, milliseconds: latestHRV.milliseconds)
    }

    var restingHRSample: RestingHRSample? {
        guard let latestRestingHR else { return nil }
        return RestingHRSample(date: latestRestingHR.date, bpm: latestRestingHR.bpm)
    }

    var weightSample: WeightSample? {
        guard let latestWeight else { return nil }
        return WeightSample(date: latestWeight.date, kilograms: latestWeight.kilograms)
    }

    private static func makeSleepNight(from aggregate: SleepNightAggregate) -> SleepNight {
        SleepNight(
            wakeDate: aggregate.wakeDate,
            sleepStart: aggregate.sleepStart,
            sleepEnd: aggregate.sleepEnd,
            totalSleepMinutes: aggregate.totalSleepMinutes,
            awakeMinutes: aggregate.awakeMinutes,
            coreMinutes: aggregate.coreMinutes,
            remMinutes: aggregate.remMinutes,
            deepMinutes: aggregate.deepMinutes,
            inBedMinutes: aggregate.inBedMinutes
        )
    }

    private static func makeHRVValue(from sample: HRVSample) -> HRVValue {
        HRVValue(date: sample.date, milliseconds: sample.milliseconds)
    }

    private static func makeRestingHRValue(from sample: RestingHRSample) -> RestingHRValue {
        RestingHRValue(date: sample.date, bpm: sample.bpm)
    }

    private static func makeWeightValue(from sample: WeightSample) -> WeightValue {
        WeightValue(date: sample.date, kilograms: sample.kilograms)
    }

    private static func mergeSleepNight(current: SleepNight?, candidate: SleepNight?) -> SleepNight? {
        guard let candidate else { return current }
        guard let current else { return candidate }
        return candidate.wakeDate >= current.wakeDate ? candidate : current
    }

    private static func mergeHRV(current: HRVValue?, candidate: HRVValue?) -> HRVValue? {
        guard let candidate else { return current }
        guard let current else { return candidate }
        return candidate.date >= current.date ? candidate : current
    }

    private static func mergeRestingHR(current: RestingHRValue?, candidate: RestingHRValue?) -> RestingHRValue? {
        guard let candidate else { return current }
        guard let current else { return candidate }
        return candidate.date >= current.date ? candidate : current
    }

    private static func mergeWeight(current: WeightValue?, candidate: WeightValue?) -> WeightValue? {
        guard let candidate else { return current }
        guard let current else { return candidate }
        return candidate.date >= current.date ? candidate : current
    }
}
