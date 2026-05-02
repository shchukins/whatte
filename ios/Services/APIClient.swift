//
//  APIClient.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

struct HealthIngestAndProcessResponse: Decodable {
    let ok: Bool
    let userId: String
    let affectedDates: [String]
    let sleepNightsCount: Int
    let restingHrCount: Int
    let hrvCount: Int
    let latestWeightIncluded: Bool
    let recoveryDaysRecomputed: Int
    let readinessDaysRecomputed: Int
}

final class APIClient {
    static let shared = APIClient()

    private init() {}

    private let baseURL = URL(string: "https://api.shchlab.ru")!

    func sendHealthPayload(
        _ payload: HealthSyncPayload,
        userID: String,
        completion: @escaping (Result<HealthIngestAndProcessResponse, Error>) -> Void
    ) {
        let url = baseURL
            .appendingPathComponent("api")
            .appendingPathComponent("v1")
            .appendingPathComponent("healthkit")
            .appendingPathComponent("full-sync")
            .appendingPathComponent(userID)

        print("health_sync_request url=\(url.absoluteString)")

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30

        let encoder = JSONEncoder()

        do {
            request.httpBody = try encoder.encode(payload)
        } catch {
            completion(.failure(error))
            return
        }

        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error {
                    print("health_sync_request network_error=\(error.localizedDescription)")
                    completion(.failure(error))
                    return
                }

                guard let httpResponse = response as? HTTPURLResponse else {
                    completion(.failure(APIError.invalidResponse))
                    return
                }

                print("health_sync_response status=\(httpResponse.statusCode)")

                guard let data else {
                    completion(.failure(APIError.emptyResponseBody))
                    return
                }

                if (200...299).contains(httpResponse.statusCode) {
                    do {
                        let decoder = JSONDecoder()
                        decoder.keyDecodingStrategy = .convertFromSnakeCase

                        let result = try decoder.decode(HealthIngestAndProcessResponse.self, from: data)
                        completion(.success(result))
                    } catch {
                        completion(.failure(error))
                    }
                } else {
                    let body = String(data: data, encoding: .utf8) ?? "n/a"
                    completion(.failure(APIError.serverError(code: httpResponse.statusCode, body: body)))
                }
            }
        }.resume()
    }
    
    func fetchReadiness(
        userID: String,
        date: String,
        completion: @escaping (Result<ReadinessDailyResponse, Error>) -> Void
    ) {
        let url = baseURL
            .appendingPathComponent("api")
            .appendingPathComponent("v1")
            .appendingPathComponent("model")
            .appendingPathComponent("readiness-daily")
            .appendingPathComponent(userID)
            .appendingPathComponent(date)

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30

        print("readiness_request url=\(url.absoluteString)")

        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error {
                    print("readiness_request network_error=\(error.localizedDescription)")
                    completion(.failure(error))
                    return
                }

                guard let httpResponse = response as? HTTPURLResponse else {
                    completion(.failure(APIError.invalidResponse))
                    return
                }

                print("readiness_response status=\(httpResponse.statusCode)")

                guard let data else {
                    completion(.failure(APIError.emptyResponseBody))
                    return
                }

                if (200...299).contains(httpResponse.statusCode) {
                    do {
                        let decoder = JSONDecoder()
                        let result = try decoder.decode(ReadinessDailyResponse.self, from: data)
                        print("readiness_decode success score=\(result.readinessScore.map { String($0) } ?? "nil")")
                        completion(.success(result))
                    } catch {
                        let body = String(data: data, encoding: .utf8) ?? "n/a"
                        print("readiness_decode error=\(error.localizedDescription)")
                        print("readiness_decode body=\(body)")
                        completion(.failure(error))
                    }
                } else {
                    let body = String(data: data, encoding: .utf8) ?? "n/a"
                    completion(.failure(APIError.serverError(code: httpResponse.statusCode, body: body)))
                }
            }
        }.resume()
    }

    func fetchReadinessHistory(
        userID: String,
        days: Int,
        completion: @escaping (Result<ReadinessHistoryResponse, Error>) -> Void
    ) {
        var components = URLComponents(
            url: baseURL
                .appendingPathComponent("api")
                .appendingPathComponent("v1")
                .appendingPathComponent("model")
                .appendingPathComponent("readiness-daily")
                .appendingPathComponent(userID)
                .appendingPathComponent("history"),
            resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "days", value: String(days))
        ]

        guard let url = components?.url else {
            completion(.failure(APIError.invalidResponse))
            return
        }

        print("readiness_history_request url=\(url.absoluteString)")

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30

        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error {
                    print("readiness_history_request network_error=\(error.localizedDescription)")
                    completion(.failure(error))
                    return
                }

                guard let httpResponse = response as? HTTPURLResponse else {
                    completion(.failure(APIError.invalidResponse))
                    return
                }

                print("readiness_history_response status=\(httpResponse.statusCode)")

                guard let data else {
                    completion(.failure(APIError.emptyResponseBody))
                    return
                }

                if (200...299).contains(httpResponse.statusCode) {
                    do {
                        let decoder = JSONDecoder()
                        let result = try decoder.decode(ReadinessHistoryResponse.self, from: data)
                        print("readiness_history_decode points_count=\(result.points.count)")
                        completion(.success(result))
                    } catch {
                        let body = String(data: data, encoding: .utf8) ?? "n/a"
                        print("readiness_history_decode error=\(error.localizedDescription)")
                        print("readiness_history_decode body=\(body)")
                        completion(.failure(error))
                    }
                } else {
                    let body = String(data: data, encoding: .utf8) ?? "n/a"
                    completion(.failure(APIError.serverError(code: httpResponse.statusCode, body: body)))
                }
            }
        }.resume()
    }
}

enum APIError: LocalizedError {
    case invalidResponse
    case emptyResponseBody
    case serverError(code: Int, body: String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid server response"
        case .emptyResponseBody:
            return "Empty server response body"
        case .serverError(let code, let body):
            return "Server error \(code): \(body)"
        }
    }
}
