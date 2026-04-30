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
    /// Tiempo MapKit asignado a este paso (proporcional a su distancia sobre la ruta).
    let durationSec: TimeInterval
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
    /// Duración total de la ruta MapKit (para repartir tiempo entre pasos).
    @State private var routeTotalDurationSec: TimeInterval = 0
    @State private var maneuverSteps: [ManeuverDisplayStep] = []
    @State private var simulatedStepIndex: Int = 0
    @State private var isLoading = false
    @State private var errorText: String?
    @StateObject private var voiceAnnouncer = NavigationVoiceAnnouncer()
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

    /// Identidad estable para disparar voz cuando cambia el consejo del tramo visible.
    private var coachingVoiceFingerprint: String {
        guard let s = coachingSegmentForBanner else { return "" }
        return "\(s.segIdx)|\(s.speechBriefForVoice)"
    }

    /// Incluye índice de paso MapKit para que cada avance dispare voz aunque el texto se parezca al anterior.
    private var maneuverVoiceFingerprint: String {
        "\(simulatedStepIndex)|\(nextStepDistanceText ?? "")|\(primaryInstruction)"
    }

    /// Tras cargar giros o activar voz, fuerza anuncio aunque la huella no haya “cambiado” en SwiftUI.
    private func pushVoiceAfterNavigationUpdate(force: Bool) {
        voiceAnnouncer.configure(
            apiKey: session.resolvedElevenLabsApiKey,
            enabled: session.voiceGuidanceEnabled
        )
        guard session.voiceGuidanceEnabled else { return }
        voiceAnnouncer.onManeuverChanged(
            stepFingerprint: maneuverVoiceFingerprint,
            distanceText: nextStepDistanceText,
            instruction: primaryInstruction,
            force: force
        )
        voiceAnnouncer.onCoachingSegmentChanged(coachingSegmentForBanner, force: force)
    }

    private func iconForCoachingAction(_ action: String?) -> String {
        switch action?.uppercased() {
        case "KEEP": return "checkmark.circle.fill"
        case "LOW_SPEED_STEADY": return "tortoise.fill"
        case "COASTING": return "sailboat.fill"
        case "WIND_COMPENSATION": return "wind"
        case "WET_EFFICIENCY": return "cloud.rain.fill"
        case "POWER_BAND": return "gauge.with.dots.needle.67percent"
        case "CLIMB_MILD": return "arrow.up.right.circle.fill"
        case "DESCENT_STEEP", "DESCENT_MODERATE": return "arrow.down.circle.fill"
        case "CRUISE_OPTIMAL": return "road.lanes"
        default: return "leaf.arrow.triangle.circlepath"
        }
    }

    private var canDebugSimulateAdvance: Bool {
        maneuverSteps.count > 1 || (coaching?.segments.count ?? 0) > 1
    }

    /// Tiempo ya “consumido” por maniobras anteriores al paso actual (`simulatedStepIndex`).
    private var consumedManeuverDurationSec: TimeInterval {
        guard simulatedStepIndex > 0 else { return 0 }
        let end = min(simulatedStepIndex, maneuverSteps.count)
        var acc: TimeInterval = 0
        for i in 0..<end {
            acc += maneuverSteps[i].durationSec
        }
        return acc
    }

    private var consumedManeuverDistanceM: CLLocationDistance {
        guard simulatedStepIndex > 0 else { return 0 }
        let end = min(simulatedStepIndex, maneuverSteps.count)
        var acc: CLLocationDistance = 0
        for i in 0..<end {
            acc += maneuverSteps[i].distanceM
        }
        return acc
    }

    private var remainingTripEtaMinutes: Int? {
        guard routeTotalDurationSec > 0, !maneuverSteps.isEmpty else { return routeEtaMinutes }
        let rem = max(0, routeTotalDurationSec - consumedManeuverDurationSec)
        return max(1, Int(round(rem / 60.0)))
    }

    private var remainingRouteKm: Double? {
        guard let totalKm = routeDistanceKm, !maneuverSteps.isEmpty else { return routeDistanceKm }
        let totalM = totalKm * 1000
        return max(0, totalM - consumedManeuverDistanceM) / 1000.0
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                mapLayer

                VStack(spacing: 0) {
                    topInstructionBanner
                    Spacer(minLength: 0)
                }
                .padding(.top, 10)

                bottomChrome
            }
            .background(Color.black)
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
                if idx == 1 {
                    voiceAnnouncer.configure(
                        apiKey: session.resolvedElevenLabsApiKey,
                        enabled: session.voiceGuidanceEnabled
                    )
                    pushVoiceAfterNavigationUpdate(force: true)
                }
                if idx != 1 {
                    voiceAnnouncer.interruptPlayback()
                }
            }
            .onAppear {
                voiceAnnouncer.configure(
                    apiKey: session.resolvedElevenLabsApiKey,
                    enabled: session.voiceGuidanceEnabled
                )
            }
            .onChange(of: session.elevenLabsApiKey) { _, _ in
                voiceAnnouncer.configure(apiKey: session.resolvedElevenLabsApiKey, enabled: session.voiceGuidanceEnabled)
                pushVoiceAfterNavigationUpdate(force: true)
            }
            .onChange(of: session.voiceGuidanceEnabled) { _, new in
                voiceAnnouncer.configure(apiKey: session.resolvedElevenLabsApiKey, enabled: new)
                if new {
                    pushVoiceAfterNavigationUpdate(force: true)
                }
            }
            .onChange(of: maneuverVoiceFingerprint) { _, _ in
                voiceAnnouncer.onManeuverChanged(
                    stepFingerprint: maneuverVoiceFingerprint,
                    distanceText: nextStepDistanceText,
                    instruction: primaryInstruction
                )
            }
            .onChange(of: coachingVoiceFingerprint) { _, _ in
                voiceAnnouncer.onCoachingSegmentChanged(coachingSegmentForBanner)
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
        HStack(alignment: .top, spacing: 12) {
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
                    let msg = seg.recommendationMessageForDisplay.trimmingCharacters(in: .whitespacesAndNewlines)
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

            VStack(spacing: 8) {
                Button {
                    Task { await loadAll() }
                } label: {
                    Group {
                        if isLoading {
                            ProgressView()
                                .tint(.white)
                                .scaleEffect(0.85)
                        } else {
                            Image(systemName: "arrow.clockwise")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(.white.opacity(0.95))
                        }
                    }
                    .frame(width: 34, height: 34)
                    .background(Color.white.opacity(0.14), in: Circle())
                }
                .buttonStyle(.plain)
                .disabled(!session.hasSelection || isLoading)
                .accessibilityLabel("Actualizar ruta y coaching")

                if session.voiceGuidanceEnabled {
                    Button {
                        voiceAnnouncer.replayLast()
                    } label: {
                        Image(systemName: "speaker.wave.2.fill")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(voiceAnnouncer.isSpeaking ? ORTATheme.accent : .white.opacity(0.95))
                            .frame(width: 34, height: 34)
                            .background(Color.white.opacity(0.14), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Repetir último anuncio de voz")
                }
            }
            .padding(.top, 2)
        }
        .padding(.leading, 14)
        .padding(.trailing, 10)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.black.opacity(0.88))
        )
        .padding(.horizontal, 10)
    }

    private var bottomChrome: some View {
        VStack(spacing: 10) {
            if let errorText {
                Text(errorText)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 8)
            }
            if let vErr = voiceAnnouncer.lastErrorDescription, !vErr.isEmpty {
                Text(vErr)
                    .font(.caption2)
                    .foregroundStyle(.orange)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 10)
            }

            if session.hasSelection {
                HStack {
                    Spacer(minLength: 0)
                    NavigationHudBar(
                        etaMinutes: remainingTripEtaMinutes,
                        routeKm: remainingRouteKm,
                        segment: coachingSegmentForBanner
                    )
                }
            }

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

            LegalDisclaimerBanner()
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
    }

    private func resetNavigationState() {
        coaching = nil
        primaryInstruction = ""
        nextStepDistanceText = nil
        routeEtaMinutes = nil
        routeDistanceKm = nil
        routeTotalDurationSec = 0
        maneuverSteps = []
        simulatedStepIndex = 0
        selectedSegIdx = nil
        voiceAnnouncer.stop()
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
                routeTotalDurationSec = 0
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
                    routeTotalDurationSec = 0
                    primaryInstruction = "Sin ruta en MapKit."
                    nextStepDistanceText = nil
                    routeEtaMinutes = nil
                    routeDistanceKm = nil
                }
                return
            }
            let steps = route.steps
            let totalD = max(route.distance, 1)
            var maneuvers: [ManeuverDisplayStep] = []
            maneuvers.reserveCapacity(steps.count)
            for step in steps {
                let t = step.instructions.trimmingCharacters(in: .whitespacesAndNewlines)
                if t.isEmpty { continue }
                let dur = route.expectedTravelTime * (step.distance / totalD)
                maneuvers.append(ManeuverDisplayStep(text: t, distanceM: step.distance, durationSec: dur))
            }
            let etaMin = max(1, Int(round(route.expectedTravelTime / 60.0)))
            let rKm = route.distance / 1000.0
            await MainActor.run {
                maneuverSteps = maneuvers
                simulatedStepIndex = 0
                routeTotalDurationSec = route.expectedTravelTime
                routeEtaMinutes = etaMin
                routeDistanceKm = rKm
                if maneuvers.isEmpty {
                    primaryInstruction = "Seguí la ruta en el mapa."
                    nextStepDistanceText = nil
                } else {
                    syncDisplayedManeuver()
                }
                pushVoiceAfterNavigationUpdate(force: true)
            }
        } catch {
            await MainActor.run {
                maneuverSteps = []
                simulatedStepIndex = 0
                routeTotalDurationSec = 0
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
