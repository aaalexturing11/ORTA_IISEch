//
//  ContentView.swift
//  ORTA_APP
//
//  Created by Alexis Aguirre Alanís on 30/04/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var session = AppSession()

    var body: some View {
        TabView {
            HomeView()
                .tabItem { Label("Ruta", systemImage: "road.lanes") }
            DriveNavigationView()
                .tabItem { Label("Navegar", systemImage: "location.north.line.fill") }
            SettingsView()
                .tabItem { Label("Ajustes", systemImage: "gearshape.fill") }
        }
        .environmentObject(session)
        .tint(ORTATheme.accent)
        .preferredColorScheme(.dark)
    }
}

#Preview {
    ContentView()
}
