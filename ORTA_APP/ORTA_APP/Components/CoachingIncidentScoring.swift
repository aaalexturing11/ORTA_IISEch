//
//  CoachingIncidentScoring.swift
//  ORTA_APP
//

import CoreLocation
import Foundation

enum CoachingMapIncidentKind: String, CaseIterable {
    case traffic
    case steepSlope
    case weather
}

/// Punto de interés en el mapa (tráfico, pendiente, clima) con prioridad por “significancia”.
struct CoachingMapIncident: Identifiable {
    var id: String { "\(segIdx)-\(kind.rawValue)" }
    let segIdx: Int
    let kind: CoachingMapIncidentKind
    let coordinate: CLLocationCoordinate2D
    let score: Double
    let tooltip: String
}

enum CoachingIncidentScoring {

    /// A mayor `latitudeDelta`, más alejado el zoom → menos marcadores.
    static func visibleIncidentCap(latitudeDelta: Double) -> Int {
        if latitudeDelta > 0.35 { return 10 }
        if latitudeDelta > 0.12 { return 28 }
        if latitudeDelta > 0.04 { return 70 }
        return 500
    }

    static func incidents(from segments: [CoachingSegment]) -> [CoachingMapIncident] {
        var out: [CoachingMapIncident] = []
        out.reserveCapacity(segments.count * 2)
        for s in segments {
            let lat = (s.startLat + s.endLat) / 2
            let lon = (s.startLon + s.endLon) / 2
            let alerts = s.alerts ?? []
            if alerts.contains("traffic") {
                let cong = s.congestionRatio ?? 1
                let score = 95 + min(45, max(0, cong - 1) * 28)
                out.append(
                    CoachingMapIncident(
                        segIdx: s.segIdx,
                        kind: .traffic,
                        coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                        score: score,
                        tooltip: "Tráfico · cong. \(String(format: "%.2f", cong))×"
                    )
                )
            }
            if alerts.contains("steep_slope") {
                let g = abs(s.slopePct)
                let score = 62 + min(48, g * 5.5)
                out.append(
                    CoachingMapIncident(
                        segIdx: s.segIdx,
                        kind: .steepSlope,
                        coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                        score: score,
                        tooltip: "Pendiente \(String(format: "%.1f", s.slopePct))%"
                    )
                )
            }
            if s.showWeatherMarker == true {
                let p = s.precipMmph ?? 0
                let w = s.windSpeedMs ?? 0
                let score = 22 + min(55, p * 16 + w * 3.2)
                let rainy = p > 0.5
                out.append(
                    CoachingMapIncident(
                        segIdx: s.segIdx,
                        kind: .weather,
                        coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                        score: score,
                        tooltip: rainy
                            ? "Lluvia \(String(format: "%.1f", p)) mm/h"
                            : "Viento \(String(format: "%.1f", w)) m/s"
                    )
                )
            }
        }
        return out.sorted { $0.score > $1.score }
    }

    static func visibleIncidents(all: [CoachingMapIncident], latitudeDelta: Double) -> [CoachingMapIncident] {
        let cap = visibleIncidentCap(latitudeDelta: latitudeDelta)
        if all.count <= cap { return all }
        return Array(all.prefix(cap))
    }

    // MARK: - Tramos coloreados (LOD por zoom)

    /// Qué tan “llamativo” es un tramo para decidir si se dibuja con zoom lejano.
    static func segmentTrailSignificance(_ s: CoachingSegment) -> Double {
        var sc = abs(s.slopePct) * 2.4
        let alerts = s.alerts ?? []
        if alerts.contains("traffic") { sc += 48 }
        if alerts.contains("steep_slope") { sc += 38 }
        if s.showWeatherMarker == true { sc += 20 }
        if let a = s.recommendationAction?.uppercased(), a != "KEEP", a != "CRUISE_OPTIMAL" { sc += 14 }
        if let c = s.congestionRatio, c > 1.15 { sc += min(30, (c - 1.15) * 40) }
        sc += min(12, (s.weight ?? 4) * 0.9)
        return sc
    }

    /// Cuántos tramos coloreados mostrar según zoom (delta de latitud del mapa).
    static func visibleColoredSegmentCap(latitudeDelta: Double) -> Int {
        if latitudeDelta > 0.42 { return 70 }
        if latitudeDelta > 0.22 { return 160 }
        if latitudeDelta > 0.10 { return 420 }
        if latitudeDelta > 0.05 { return 1100 }
        if latitudeDelta > 0.028 { return 2200 }
        return 500_000
    }

    static func routeOutlineCoordinates(segments: [CoachingSegment]) -> [CLLocationCoordinate2D] {
        let sorted = segments.sorted { $0.segIdx < $1.segIdx }
        var coords: [CLLocationCoordinate2D] = []
        coords.reserveCapacity(sorted.count * 2)
        for s in sorted {
            let p = s.coordinatePair
            if coords.isEmpty { coords.append(p[0]) }
            coords.append(p[1])
        }
        return coords
    }

    static func visibleColoredSegments(_ segments: [CoachingSegment], latitudeDelta: Double) -> [CoachingSegment] {
        let cap = visibleColoredSegmentCap(latitudeDelta: latitudeDelta)
        guard segments.count > cap else {
            return segments.sorted { $0.segIdx < $1.segIdx }
        }
        let scored = segments.map { ($0, segmentTrailSignificance($0)) }
        let topIdx = Set(scored.sorted { $0.1 > $1.1 }.prefix(cap).map { $0.0.segIdx })
        return segments.filter { topIdx.contains($0.segIdx) }.sorted { $0.segIdx < $1.segIdx }
    }
}
