//
//  ReadinessModels.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 17.04.2026.
//

import Foundation

struct ReadinessDailyResponse: Decodable {
    let ok: Bool?
    let userID: String?
    let date: String?
    let readinessScore: Double?
    let goodDayProbability: Double?
    let statusText: String?
    let recommendation: String?
    let reason: String?
    let briefing: String?
    let readinessComment: String?
    let briefingText: String?
    let explanation: ReadinessExplanation?

    private enum CodingKeys: String, CodingKey {
        case ok
        case userID = "user_id"
        case date
        case readinessScore = "readiness_score"
        case goodDayProbability = "good_day_probability"
        case statusText = "status_text"
        case recommendation
        case reason
        case briefing
        case readinessComment = "readiness_comment"
        case briefingText = "briefing_text"
        case explanation
        case explanationJSON = "explanation_json"
        case freshness
        case freshnessNorm = "freshness_norm"
        case recoveryScoreSimple = "recovery_score_simple"
        case formula
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        ok = try container.decodeIfPresent(Bool.self, forKey: .ok)
        userID = try container.decodeIfPresent(String.self, forKey: .userID)
        date = try container.decodeIfPresent(String.self, forKey: .date)
        readinessScore = try container.decodeIfPresent(Double.self, forKey: .readinessScore)
        goodDayProbability = try container.decodeIfPresent(Double.self, forKey: .goodDayProbability)
        statusText = try container.decodeIfPresent(String.self, forKey: .statusText)
        recommendation = try container.decodeIfPresent(String.self, forKey: .recommendation)
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        briefing = try container.decodeIfPresent(String.self, forKey: .briefing)
        readinessComment = try container.decodeIfPresent(String.self, forKey: .readinessComment)
        briefingText = try container.decodeIfPresent(String.self, forKey: .briefingText)

        if let explanation = try container.decodeIfPresent(ReadinessExplanation.self, forKey: .explanation) {
            self.explanation = explanation
        } else if let explanationJSON = try container.decodeIfPresent(ReadinessExplanation.self, forKey: .explanationJSON) {
            self.explanation = explanationJSON
        } else {
            let freshness = try container.decodeIfPresent(Double.self, forKey: .freshness)
            let freshnessNorm = try container.decodeIfPresent(Double.self, forKey: .freshnessNorm)
            let recoveryScoreSimple = try container.decodeIfPresent(Double.self, forKey: .recoveryScoreSimple)
            let formula = try container.decodeIfPresent(String.self, forKey: .formula)

            if freshness != nil || freshnessNorm != nil || recoveryScoreSimple != nil || formula != nil {
                self.explanation = ReadinessExplanation(
                    freshness: freshness,
                    freshnessNorm: freshnessNorm,
                    recoveryScoreSimple: recoveryScoreSimple,
                    formula: formula,
                    recoveryExplanation: nil
                )
            } else {
                self.explanation = nil
            }
        }
    }
}

struct ReadinessHistoryResponse: Decodable {
    let ok: Bool
    let userID: String
    let days: Int
    let points: [ReadinessHistoryItem]

    enum CodingKeys: String, CodingKey {
        case ok
        case userID = "user_id"
        case days
        case points
    }
}

struct ReadinessHistoryItem: Decodable, Identifiable {
    let date: String
    let readinessScore: Double?
    let statusText: String?
    let goodDayProbability: Double?
    let explanation: ReadinessExplanation?

    var id: String { date }

    enum CodingKeys: String, CodingKey {
        case date
        case readinessScore = "readiness_score"
        case statusText = "status_text"
        case goodDayProbability = "good_day_probability"
        case explanation
    }
}

struct ReadinessExplanation: Decodable {
    let freshness: Double?
    let freshnessNorm: Double?
    let recoveryScoreSimple: Double?
    let formula: String?
    let recoveryExplanation: RecoveryExplanation?

    enum CodingKeys: String, CodingKey {
        case freshness
        case freshnessNorm = "freshness_norm"
        case recoveryScoreSimple = "recovery_score_simple"
        case formula
        case recoveryExplanation = "recovery_explanation"
    }
}

struct RecoveryExplanation: Decodable {
    let method: String?
    let sleepMinutes: Double?
    let hrvToday: Double?
    let rhrToday: Double?
    let hrvBaseline: Double?
    let rhrBaseline: Double?
    let hrvDev: Double?
    let rhrDev: Double?
    let sleepScore: Double?
    let hrvScore: Double?
    let rhrScore: Double?
    let recoveryScoreSimple: Double?

    enum CodingKeys: String, CodingKey {
        case method
        case sleepMinutes = "sleep_minutes"
        case hrvToday = "hrv_today"
        case rhrToday = "rhr_today"
        case hrvBaseline = "hrv_baseline"
        case rhrBaseline = "rhr_baseline"
        case hrvDev = "hrv_dev"
        case rhrDev = "rhr_dev"
        case sleepScore = "sleep_score"
        case hrvScore = "hrv_score"
        case rhrScore = "rhr_score"
        case recoveryScoreSimple = "recovery_score_simple"
    }
}
