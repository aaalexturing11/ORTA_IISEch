//
//  DriveNavigationView.swift
//  ORTA_APP
//

import CoreLocation
import MapKit
import SwiftUI

struct DriveNavigationView: View {
    @EnvironmentObject private var session: AppSession
    @State private var position: MapCameraPosition = .automatic
    @State private var selectedSegIdx: Int?
    @State private var coaching: CoachingResponse?
    @State private var turnSteps: [String] = []
    @State private var isLoading = false
    @State private var errorText: String?
    private let locationManager = CLLocationManager()

    private var selectedSegment: CoachingSegment? {
        guard let idx = selectedSegIdx,
              let list = coaching?.segments,
              let s = list.first(where: { $0.segIdx == idx }) else { return nil }
        return s
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                if session.hasSelection, let c = coaching, !(c.segments.isEmpty) {
                    CoachingMapView(
                        segments: c.segments,
                        origin: c.origin,
                        destination: c.destination,
                        position: $position,
                        selectedSegIdx: $selectedSegIdx
                    )
                    .ignoresSafeArea(edges: .top)
                } else {
                    ContentUnavailableView(
                        "Sin ruta",
                        systemImage: "map",
                        description: Text("Elegí ruta y camión en la pestaña inicio y tocá «Cargar mapa».")
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(ORTATheme.bg)
                }

                VStack(spacing: 10) {
                    if let errorText {
                        Text(errorText)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding(.horizontal)
                    }
                    TurnStepsStrip(steps: turnSteps)
                        .padding(12)
                        .background(RoundedRectangle(cornerRadius: 14).fill(ORTATheme.card.opacity(0.95)))

                    CoachBottomCard(segment: selectedSegment)
                    LegalDisclaimerBanner()
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
            }
            .background(ORTATheme.bg)
            .navigationTitle("Navegación")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await loadAll() }
                    } label: {
                        if isLoading {
                            ProgressView()
                        } else {
                            Label("Cargar mapa", systemImage: "arrow.triangle.2.circlepath")
                        }
                    }
                    .disabled(!session.hasSelection || isLoading)
                }
            }
            .task {
                locationManager.requestWhenInUseAuthorization()
                if session.hasSelection {
                    await loadAll()
                }
            }
            .onChange(of: session.selectedRouteSlug) { _, _ in
                coaching = nil
                turnSteps = []
                selectedSegIdx = nil
            }
            .onChange(of: session.selectedTruckSlug) { _, _ in
                coaching = nil
                turnSteps = []
                selectedSegIdx = nil
            }
        }
    }

    private func loadAll() async {
        guard let rs = session.selectedRouteSlug, let ts = session.selectedTruckSlug else { return }
        isLoading = true
        errorText = nil
        defer { isLoading = false }
        let api = ORTAAPIService(baseURL: session.apiBaseURL)
        do {
            let c = try await api.fetchCoaching(route: rs, truck: ts)
            await MainActor.run {
                coaching = c
                if !c.segments.isEmpty {
                    position = MapBounds.camera(for: c.segments)
                }
            }
            await loadTurnSteps(from: c)
        } catch {
            await MainActor.run { errorText = error.localizedDescription }
        }
    }

    private func loadTurnSteps(from coaching: CoachingResponse) async {
        guard let o = coaching.origin, let d = coaching.destination else {
            await MainActor.run { turnSteps = [] }
            return
        }
        let req = MKDirections.Request()
        req.source = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: o.lat, longitude: o.lon)))
        req.destination = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: d.lat, longitude: d.lon)))
        req.transportType = .automobile
        let directions = MKDirections(request: req)
        do {
            let response = try await directions.calculate()
            let steps = response.routes.first?.steps ?? []
            let lines = steps.compactMap { step -> String? in
                let t = step.instructions.trimmingCharacters(in: .whitespacesAndNewlines)
                return t.isEmpty ? nil : t
            }
            await MainActor.run { turnSteps = lines }
        } catch {
            await MainActor.run { turnSteps = [] }
        }
    }
}

#Preview {
    DriveNavigationView()
        .environmentObject(AppSession())
}
