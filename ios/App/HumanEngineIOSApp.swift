//
//  HumanEngineIOSApp.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 05.04.2026.
//

import SwiftUI

@main
struct HumanEngineIOSApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onAppear {
                    SyncCoordinator.shared.start()
                }
                .onChange(of: scenePhase) { _, newPhase in
                    guard newPhase == .active else { return }
                    SyncCoordinator.shared.handleAppBecameActive()
                }
        }
    }
}
