//
//  Notifications.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 06.04.2026.
//

import Foundation

extension Notification.Name {
    static let healthKitHRVUpdated = Notification.Name("healthKitHRVUpdated")
    static let healthKitRestingHRUpdated = Notification.Name("healthKitRestingHRUpdated")
    static let healthKitSleepUpdated = Notification.Name("healthKitSleepUpdated")
    static let autoSyncDidFinish = Notification.Name("autoSyncDidFinish")
    static let syncStateDidChange = Notification.Name("syncStateDidChange")
}
