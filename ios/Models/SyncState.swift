//
//  SyncState.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

enum SyncMode: String, Codable {
    case full
    case incremental
    case backfill
}

struct SyncState: Codable {
    var lastSyncAttemptAt: Date?
    var lastSuccessfulSyncAt: Date?
    var lastPayloadGeneratedAt: Date?
    var lastErrorMessage: String?
    var lastSentItemCount: Int = 0
    var lastSyncMode: SyncMode?
    var hasPendingAutoSync: Bool = false

    static let empty = SyncState()
}
