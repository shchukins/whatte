//
//  HumanEngineIOSApp.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 05.04.2026.
//

import SwiftUI

@main
struct HumanEngineIOSApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .onAppear {
                    SyncCoordinator.shared.start()
                }
        }
    }
}
