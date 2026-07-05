//
//  SyncStateStore.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

final class SyncStateStore {
    static let shared = SyncStateStore()

    private let userDefaults: UserDefaults
    private let storageKey = "human_engine.sync_state"

    private init(userDefaults: UserDefaults = .standard) {
        self.userDefaults = userDefaults
    }

    func load() -> SyncState {
        guard let data = userDefaults.data(forKey: storageKey) else {
            return .empty
        }

        do {
            return try JSONDecoder().decode(SyncState.self, from: data)
        } catch {
            return .empty
        }
    }

    func save(_ state: SyncState) {
        do {
            let data = try JSONEncoder().encode(state)
            userDefaults.set(data, forKey: storageKey)
        } catch {
            print("Failed to save SyncState: \(error.localizedDescription)")
        }
    }

    func clear() {
        userDefaults.removeObject(forKey: storageKey)
    }
}

final class LatestHealthSnapshotStore {
    static let shared = LatestHealthSnapshotStore()

    private let userDefaults: UserDefaults
    private let storageKey = "human_engine.latest_health_snapshot"

    private init(userDefaults: UserDefaults = .standard) {
        self.userDefaults = userDefaults
    }

    func load() -> LatestHealthSnapshot? {
        guard let data = userDefaults.data(forKey: storageKey) else {
            return nil
        }

        do {
            return try JSONDecoder().decode(LatestHealthSnapshot.self, from: data)
        } catch {
            return nil
        }
    }

    func save(_ snapshot: LatestHealthSnapshot) {
        do {
            let data = try JSONEncoder().encode(snapshot)
            userDefaults.set(data, forKey: storageKey)
        } catch {
            print("Failed to save LatestHealthSnapshot: \(error.localizedDescription)")
        }
    }
}
