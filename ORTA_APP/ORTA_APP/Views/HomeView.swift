//
//  HomeView.swift
//  ORTA_APP
//

import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: AppSession
    @State private var routes: [ORTARouteSummary] = []
    @State private var kpis: KPIsResponse?
    @State private var isLoadingRoutes = false
    @State private var isLoadingKpis = false
    @State private var errorText: String?

    private var selectedRoute: ORTARouteSummary? {
        routes.first { $0.slug == session.selectedRouteSlug }
    }

    private var litersEstimate: Double? {
        guard let d = selectedRoute?.distanceKm, d > 0,
              let f = kpis?.fuelLPer100km, f > 0 else { return nil }
        return d * f / 100.0
    }

    private var costMXN: Double? {
        guard let l = litersEstimate else { return nil }
        return l * session.dieselPriceMXNPerL
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text("Marcá origen, destino y unidad. Te mostramos km y litros; después abrís el mapa.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    if let errorText {
                        Label(errorText, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }

                    Text("Tu ruta")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(ORTATheme.textSecondary)

                    if isLoadingRoutes && routes.isEmpty {
                        ProgressView("Cargando rutas…")
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 24)
                    } else if routes.isEmpty {
                        ContentUnavailableView(
                            "Sin rutas",
                            systemImage: "mappin.slash",
                            description: Text("Encendé el servidor ORTA en Ajustes.")
                        )
                        .frame(minHeight: 120)
                    } else {
                        VStack(spacing: 10) {
                            ForEach(routes) { r in
                                routeCard(r)
                            }
                        }
                    }

                    if selectedRoute != nil {
                        truckSection
                    }

                    if session.hasSelection {
                        summarySection
                        openMapButton
                    }

                    LegalDisclaimerBanner()
                }
                .padding(16)
            }
            .background(ORTATheme.bg.ignoresSafeArea())
            .navigationTitle("Planear viaje")
            .toolbarBackground(ORTATheme.card, for: .navigationBar)
            .task { await loadRoutes() }
            .task(id: "\(session.selectedRouteSlug ?? "")-\(session.selectedTruckSlug ?? "")") {
                await refreshKPIsIfPossible()
            }
            .onChange(of: session.selectedRouteSlug) { _, _ in
                syncTruckIfNeeded()
                kpis = nil
            }
            .onChange(of: session.apiBaseURL) { _, _ in
                Task { await loadRoutes() }
            }
        }
    }

    private func routeCard(_ r: ORTARouteSummary) -> some View {
        let selected = r.slug == session.selectedRouteSlug
        return Button {
            session.selectedRouteSlug = r.slug
            syncTruckIfNeeded()
        } label: {
            HStack(alignment: .top, spacing: 14) {
                VStack(spacing: 10) {
                    Image(systemName: "mappin.circle.fill")
                        .font(.title2)
                        .foregroundStyle(.green)
                    Image(systemName: "arrow.down")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.tertiary)
                    Image(systemName: "flag.checkered")
                        .font(.title2)
                        .foregroundStyle(.red)
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text(r.origin ?? "Origen")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)
                    Text(r.destination ?? "Destino")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)
                    if let km = r.distanceKm {
                        Label(String(format: "%.0f km", km), systemImage: "road.lanes")
                            .font(.caption)
                            .foregroundStyle(ORTATheme.accent)
                    }
                }
                Spacer(minLength: 0)
                if selected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title2)
                        .foregroundStyle(ORTATheme.accent)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(ORTATheme.card)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(selected ? ORTATheme.accent.opacity(0.85) : Color.white.opacity(0.06), lineWidth: selected ? 2 : 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }

    private var truckSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Tu unidad")
                .font(.caption.weight(.semibold))
                .foregroundStyle(ORTATheme.textSecondary)
            let trucks = selectedRoute?.trucks ?? []
            if trucks.isEmpty {
                Text("Esta ruta no tiene camiones configurados.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(trucks) { t in
                            let on = t.slug == session.selectedTruckSlug
                            Button {
                                session.selectedTruckSlug = t.slug
                            } label: {
                                VStack(spacing: 6) {
                                    Image(systemName: "truck.box.fill")
                                        .font(.title2)
                                    Text(t.label ?? t.slug)
                                        .font(.caption)
                                        .lineLimit(2)
                                        .multilineTextAlignment(.center)
                                }
                                .frame(width: 100, height: 88)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(on ? ORTATheme.accent.opacity(0.22) : ORTATheme.card)
                                )
                                .overlay(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .stroke(on ? ORTATheme.accent : Color.white.opacity(0.06), lineWidth: on ? 2 : 1)
                                )
                                .foregroundStyle(on ? Color.white : Color.primary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var summarySection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Resumen del viaje", systemImage: "gauge.with.dots.needle.67percent")
                .font(.headline)
                .foregroundStyle(ORTATheme.accent)

            HStack(spacing: 0) {
                statBlock(
                    icon: "road.lanes",
                    title: "Distancia",
                    value: selectedRoute?.distanceKm.map { String(format: "%.0f km", $0) } ?? "—"
                )
                Divider().frame(height: 44).background(Color.white.opacity(0.15))
                statBlock(
                    icon: "fuelpump.fill",
                    title: "Diesel (aprox.)",
                    value: litersEstimate.map { String(format: "%.1f L", $0) } ?? (isLoadingKpis ? "…" : "—")
                )
            }
            .padding(.vertical, 8)

            if let c = costMXN {
                Label(String(format: "≈ $%.0f MXN al precio que pusiste", c), systemImage: "pesosign.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let f = kpis?.fuelLPer100km {
                Text(String(format: "Histórico ORTA: %.1f L/100 km para esta ruta y camión.", f))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            } else if !isLoadingKpis {
                Text("Cuando el servidor tenga datos de simulación, verás los litros aquí.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            Button {
                Task { await refreshKPIsIfPossible(force: true) }
            } label: {
                Label("Actualizar litros", systemImage: "arrow.clockwise")
                    .font(.subheadline.weight(.medium))
            }
            .buttonStyle(.bordered)
            .disabled(isLoadingKpis)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(ORTATheme.card)
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.white.opacity(0.07), lineWidth: 1)
                )
        )
    }

    private func statBlock(icon: String, title: String, value: String) -> some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(ORTATheme.accent)
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.weight(.bold))
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity)
    }

    private var openMapButton: some View {
        Button {
            session.selectedMainTabIndex = 1
        } label: {
            Label("Abrir mapa y maniobras", systemImage: "map.fill")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
        }
        .buttonStyle(.borderedProminent)
        .tint(ORTATheme.accent)
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
        isLoadingRoutes = true
        errorText = nil
        defer { isLoadingRoutes = false }
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

    private func refreshKPIsIfPossible(force: Bool = false) async {
        guard let rs = session.selectedRouteSlug, let ts = session.selectedTruckSlug else { return }
        if !force, kpis != nil { return }
        isLoadingKpis = true
        defer { isLoadingKpis = false }
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
