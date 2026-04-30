//
//  HomeView.swift
//  ORTA_APP
//

import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: AppSession
    @State private var routes: [ORTARouteSummary] = []
    @State private var kpis: KPIsResponse?
    @State private var isLoading = false
    @State private var errorText: String?

    private var selectedRoute: ORTARouteSummary? {
        routes.first { $0.slug == session.selectedRouteSlug }
    }

    private var routeLabel: String {
        guard let r = selectedRoute else { return "—" }
        let o = r.origin ?? "Origen"
        let d = r.destination ?? "Destino"
        return "\(o) → \(d)"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Elegí ruta y unidad; los avisos eco salen del mismo backend que el mapa de coaching.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    if let errorText {
                        Text(errorText)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    Group {
                        Text("Ruta")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Ruta", selection: Binding(
                            get: { session.selectedRouteSlug ?? "" },
                            set: { session.selectedRouteSlug = $0.isEmpty ? nil : $0 }
                        )) {
                            Text("—").tag("")
                            ForEach(routes) { r in
                                Text(shortRouteTitle(r)).tag(r.slug)
                            }
                        }
                        .pickerStyle(.menu)

                        Text("Camión")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Picker("Camión", selection: Binding(
                            get: { session.selectedTruckSlug ?? "" },
                            set: { session.selectedTruckSlug = $0.isEmpty ? nil : $0 }
                        )) {
                            Text("—").tag("")
                            ForEach(selectedRoute?.trucks ?? []) { t in
                                Text(t.label ?? t.slug).tag(t.slug)
                            }
                        }
                        .pickerStyle(.menu)
                        .disabled(selectedRoute == nil)
                    }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 14).fill(ORTATheme.card))

                    Button {
                        Task { await refreshKPIs() }
                    } label: {
                        Label("Actualizar estimación de combustible", systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(ORTATheme.accent)
                    .disabled(!session.hasSelection || isLoading)

                    FuelEstimateCard(
                        routeLabel: routeLabel,
                        distanceKm: selectedRoute?.distanceKm,
                        fuelLPer100km: kpis?.fuelLPer100km,
                        dieselPriceMXNPerL: session.dieselPriceMXNPerL,
                        nTripsSample: kpis?.nTrips
                    )

                    LegalDisclaimerBanner()
                }
                .padding(16)
            }
            .background(ORTATheme.bg.ignoresSafeArea())
            .navigationTitle("ORTA")
            .toolbarBackground(ORTATheme.card, for: .navigationBar)
            .task { await loadRoutes() }
            .onChange(of: session.selectedRouteSlug) { _, _ in
                syncTruckIfNeeded()
                kpis = nil
            }
            .onChange(of: session.apiBaseURL) { _, _ in
                Task { await loadRoutes() }
            }
        }
    }

    private func shortRouteTitle(_ r: ORTARouteSummary) -> String {
        let km = r.distanceKm.map { String(format: " · %.0f km", $0) } ?? ""
        let o = (r.origin ?? "").prefix(18)
        let d = (r.destination ?? "").prefix(18)
        return "\(o) → \(d)\(km)"
    }

    private func syncTruckIfNeeded() {
        guard let r = selectedRoute else {
            session.selectedTruckSlug = nil
            return
        }
        let trucks = r.trucks
        guard !trucks.isEmpty else {
            session.selectedTruckSlug = nil
            return
        }
        if let cur = session.selectedTruckSlug, trucks.contains(where: { $0.slug == cur }) {
            return
        }
        session.selectedTruckSlug = trucks.first?.slug
    }

    private func loadRoutes() async {
        isLoading = true
        errorText = nil
        defer { isLoading = false }
        let api = ORTAAPIService(baseURL: session.apiBaseURL)
        do {
            let list = try await api.fetchRoutes()
            await MainActor.run {
                routes = list
                if session.selectedRouteSlug == nil, let first = list.first {
                    session.selectedRouteSlug = first.slug
                }
                syncTruckIfNeeded()
            }
        } catch {
            await MainActor.run { errorText = error.localizedDescription }
        }
    }

    private func refreshKPIs() async {
        guard let rs = session.selectedRouteSlug, let ts = session.selectedTruckSlug else { return }
        isLoading = true
        errorText = nil
        defer { isLoading = false }
        let api = ORTAAPIService(baseURL: session.apiBaseURL)
        do {
            let k = try await api.fetchKPIs(route: rs, truck: ts)
            await MainActor.run { kpis = k }
        } catch {
            await MainActor.run { errorText = error.localizedDescription }
        }
    }
}

#Preview {
    HomeView()
        .environmentObject(AppSession())
}
