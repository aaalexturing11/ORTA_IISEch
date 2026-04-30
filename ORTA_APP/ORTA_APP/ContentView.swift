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
        TabView(selection: $session.selectedMainTabIndex) {
            HomeView()
                .tabItem { Label("Viaje", systemImage: "point.topleft.down.curvedto.point.bottomright.up") }
                .tag(0)
            DriveNavigationView()
                .tabItem { Label("Mapa", systemImage: "map.fill") }
                .tag(1)
            SettingsView()
                .tabItem { Label("Ajustes", systemImage: "gearshape.fill") }
                .tag(2)
        }
        .environmentObject(session)
        .tint(ORTATheme.accent)
        .preferredColorScheme(.dark)
    }
}

#Preview {
    ContentView()
}
