//
//  DriveNavigationView.swift
//  ORTA_APP
//

import CoreLocation
import MapKit
import SwiftUI

private struct ManeuverDisplayStep: Equatable {
    let text: String
    let distanceM: CLLocationDistance
}

struct DriveNavigationView: View {
    @EnvironmentObject private var session: AppSession
    @State private var position: MapCameraPosition = .automatic
    @State private var selectedSegIdx: Int?
    @State private var coaching: CoachingResponse?
    @State private var primaryInstruction: String = ""
    @State private var nextStepDistanceText: String?
    @State private var routeEtaMinutes: Int?
    @State private var routeDistanceKm: Double?
    @State private var maneuverSteps: [ManeuverDisplayStep] = []
    @State private var simulatedStepIndex: Int = 0
    @State private var isLoading = false
    @State private var errorText: String?
    private let locationManager = CLLocationManager()

    private var selectedSegment: CoachingSegment? {
        guard let idx = selectedSegIdx,
              let list = coaching?.segments,
              let s = list.first(where: { $0.segIdx == idx }) else { return nil }
        return s
    }

    /// Tramo usado para el aviso ORTA en el banner: el seleccionado en el mapa o el primero por `seg_idx`.
    private var coachingSegmentForBanner: CoachingSegment? {
        guard let list = coaching?.segments, !list.isEmpty else { return nil }
        if let idx = selectedSegIdx, let s = list.first(where: { $0.segIdx == idx }) {
            return s
        }
        return list.min(by: { $0.segIdx < $1.segIdx })
    }

    private func iconForCoachingAction(_ action: String?) -> String {
        switch action?.uppercased() {
        case "KEEP": return "checkmark.circle.fill"
        case "LOW_SPEED_STEADY": return "tortoise.fill"
        case "COASTING": return "sailboat.fill"
        case "WIND_COMPENSATION": return "wind"
        case "WET_EFFICIENCY": return "cloud.rain.fill"
        case "POWER_BAND": return "gauge.with.dots.needle.67percent"
        default: return "leaf.arrow.triangle.circlepath"
        }
    }

    private var canDebugSimulateAdvance: Bool {
        maneuverSteps.count > 1 || (coaching?.segments.count ?? 0) > 1
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                mapLayer

                VStack(spacing: 0) {
                    topInstructionBanner
                    Spacer(minLength: 0)
                }
                .padding(.top, 6)

                bottomChrome
            }
            .background(Color.black)
            .overlay(alignment: .topTrailing) {
                Button {
                    Task { await loadAll() }
                } label: {
                    Group {
                        if isLoading {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "arrow.clockwise")
                                .font(.title3.weight(.semibold))
                                .foregroundStyle(.white)
                        }
                    }
                    .frame(width: 44, height: 44)
                    .background(.ultraThinMaterial, in: Circle())
                }
                .disabled(!session.hasSelection || isLoading)
                .padding(.trailing, 12)
                .padding(.top, 52)
            }
            .task {
                locationManager.requestWhenInUseAuthorization()
                if session.hasSelection {
                    await loadAll()
                }
            }
            .onChange(of: session.selectedRouteSlug) { _, _ in
                resetNavigationState()
                Task { await loadAll() }
            }
            .onChange(of: session.selectedTruckSlug) { _, _ in
                resetNavigationState()
                Task { await loadAll() }
            }
            .onChange(of: session.selectedMainTabIndex) { _, idx in
                if idx == 1, session.hasSelection, coaching == nil {
                    Task { await loadAll() }
                }
            }
        }
        .toolbar(.hidden, for: .navigationBar)
    }

    @ViewBuilder
    private var mapLayer: some View {
        if session.hasSelection, let c = coaching, !c.segments.isEmpty {
            CoachingMapView(
                segments: c.segments,
                origin: c.origin,
                destination: c.destination,
                position: $position,
                selectedSegIdx: $selectedSegIdx
            )
            .ignoresSafeArea()
        } else {
            ContentUnavailableView(
                "Sin ruta",
                systemImage: "map",
                description: Text("En la pestaña Viaje elegí trayecto y unidad, después volvé acá.")
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(ORTATheme.bg)
        }
    }

    private var topInstructionBanner: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let t = nextStepDistanceText, !t.isEmpty {
                Text(t)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(ORTATheme.accent)
            }
            Text(primaryInstruction.isEmpty ? "Calculando maniobra…" : primaryInstruction)
                .font(.title3.weight(.bold))
                .foregroundStyle(.white)
                .multilineTextAlignment(.leading)
                .minimumScaleFactor(0.75)

            if let seg = coachingSegmentForBanner {
                let msg = (seg.recommendationMessage ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !msg.isEmpty {
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: iconForCoachingAction(seg.recommendationAction))
                            .font(.title3)
                            .foregroundStyle(Color(red: 0.45, green: 0.92, blue: 0.72))
                            .frame(width: 28, alignment: .center)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Consejo ORTA (tramo \(seg.segIdx))")
                                .font(.caption2.weight(.semibold))
                                .foregroundStyle(.white.opacity(0.55))
                            Text(msg)
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(Color(red: 0.82, green: 0.96, blue: 0.9))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.top, 8)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.black.opacity(0.88))
        )
        .padding(.horizontal, 10)
        .overlay(alignment: .bottomTrailing) {
            #if DEBUG
            if canDebugSimulateAdvance {
                Button {
                    advanceSimulatedManeuver()
                } label: {
                    Image(systemName: "arrowtriangle.right.fill")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.black)
                        .frame(width: 32, height: 28)
                        .background(Color.yellow, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .accessibilityLabel("Simular siguiente maniobra (debug)")
                .padding(8)
            }
            #endif
        }
    }

    private var bottomChrome: some View {
        VStack(spacing: 10) {
            if let errorText {
                Text(errorText)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 8)
            }

            tripSummaryBar

            #if DEBUG
            if canDebugSimulateAdvance {
                HStack(spacing: 8) {
                    Image(systemName: "ladybug.fill")
                        .foregroundStyle(.yellow)
                    Text("Debug: calle \(simulatedStepIndex + 1)/\(maneuverSteps.count) · ORTA tramo \(selectedSegIdx.map(String.init) ?? "—")")
                        .font(.caption2.monospacedDigit())
                    Spacer(minLength: 0)
                    Button("Siguiente") {
                        advanceSimulatedManeuver()
                    }
                    .font(.caption.weight(.semibold))
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.orange.opacity(0.18))
                )
            }
            #endif

            CoachBottomCard(segment: selectedSegment)

            LegalDisclaimerBanner()
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
    }

    private var tripSummaryBar: some View {
        HStack(spacing: 16) {
            Image(systemName: "clock.fill")
                .font(.title3)
                .foregroundStyle(ORTATheme.accent)
            VStack(alignment: .leading, spacing: 2) {
                if let m = routeEtaMinutes {
                    Text("~\(m) min")
                        .font(.headline.weight(.bold))
                        .foregroundStyle(.primary)
                } else {
                    Text("—")
                        .font(.headline)
                        .foregroundStyle(.secondary)
                }
                if let km = routeDistanceKm {
                    Text(String(format: "%.1f km en ruta (MapKit)", km))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.up.circle.fill")
                .font(.title2)
                .foregroundStyle(.secondary.opacity(0.6))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(red: 0.96, green: 0.97, blue: 0.99))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.black.opacity(0.06), lineWidth: 1)
        )
        .environment(\.colorScheme, .light)
    }

    private func resetNavigationState() {
        coaching = nil
        primaryInstruction = ""
        nextStepDistanceText = nil
        routeEtaMinutes = nil
        routeDistanceKm = nil
        maneuverSteps = []
        simulatedStepIndex = 0
        selectedSegIdx = nil
    }

    private static func formatStepDistance(_ m: CLLocationDistance) -> String? {
        guard m > 0 else { return nil }
        if m >= 1000 {
            return String(format: "%.1f km", m / 1000)
        }
        return String(format: "%.0f m", m)
    }

    private func syncDisplayedManeuver() {
        guard !maneuverSteps.isEmpty else { return }
        let i = min(max(0, simulatedStepIndex), maneuverSteps.count - 1)
        let s = maneuverSteps[i]
        primaryInstruction = s.text
        nextStepDistanceText = Self.formatStepDistance(s.distanceM)
    }

    private func advanceSimulatedManeuver() {
        if maneuverSteps.count > 1 {
            simulatedStepIndex = (simulatedStepIndex + 1) % maneuverSteps.count
            syncDisplayedManeuver()
        }
        if (coaching?.segments.count ?? 0) > 1 {
            advanceCoachingSegmentForDebug()
        }
    }

    /// En debug, al avanzar calle también rotamos el tramo ORTA resaltado para ver otros consejos.
    private func advanceCoachingSegmentForDebug() {
        guard let segs = coaching?.segments, !segs.isEmpty else { return }
        let sortedIdx = segs.map(\.segIdx).sorted()
        guard let first = sortedIdx.first else { return }
        if let cur = selectedSegIdx, let i = sortedIdx.firstIndex(of: cur) {
            selectedSegIdx = sortedIdx[(i + 1) % sortedIdx.count]
        } else {
            selectedSegIdx = first
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
                    selectedSegIdx = c.segments.map(\.segIdx).min()
                } else {
                    selectedSegIdx = nil
                }
            }
            await loadTurnSteps(from: c)
        } catch {
            await MainActor.run { errorText = error.localizedDescription }
        }
    }

    private func loadTurnSteps(from coaching: CoachingResponse) async {
        guard let o = coaching.origin, let d = coaching.destination else {
            await MainActor.run {
                maneuverSteps = []
                simulatedStepIndex = 0
                primaryInstruction = "No hay coordenadas para indicaciones."
                nextStepDistanceText = nil
                routeEtaMinutes = nil
                routeDistanceKm = nil
            }
            return
        }
        let req = MKDirections.Request()
        req.source = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: o.lat, longitude: o.lon)))
        req.destination = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: d.lat, longitude: d.lon)))
        req.transportType = .automobile
        let directions = MKDirections(request: req)
        do {
            let response = try await directions.calculate()
            guard let route = response.routes.first else {
                await MainActor.run {
                    maneuverSteps = []
                    simulatedStepIndex = 0
                    primaryInstruction = "Sin ruta en MapKit."
                    nextStepDistanceText = nil
                    routeEtaMinutes = nil
                    routeDistanceKm = nil
                }
                return
            }
            let steps = route.steps
            var maneuvers: [ManeuverDisplayStep] = []
            maneuvers.reserveCapacity(steps.count)
            for step in steps {
                let t = step.instructions.trimmingCharacters(in: .whitespacesAndNewlines)
                if t.isEmpty { continue }
                maneuvers.append(ManeuverDisplayStep(text: t, distanceM: step.distance))
            }
            let etaMin = max(1, Int(round(route.expectedTravelTime / 60.0)))
            let rKm = route.distance / 1000.0
            await MainActor.run {
                maneuverSteps = maneuvers
                simulatedStepIndex = 0
                routeEtaMinutes = etaMin
                routeDistanceKm = rKm
                if maneuvers.isEmpty {
                    primaryInstruction = "Seguí la ruta en el mapa."
                    nextStepDistanceText = nil
                } else {
                    syncDisplayedManeuver()
                }
            }
        } catch {
            await MainActor.run {
                maneuverSteps = []
                simulatedStepIndex = 0
                primaryInstruction = "No se pudieron cargar giros."
                nextStepDistanceText = nil
                routeEtaMinutes = nil
                routeDistanceKm = nil
            }
        }
    }
}

#Preview {
    DriveNavigationView()
        .environmentObject(AppSession())
}
