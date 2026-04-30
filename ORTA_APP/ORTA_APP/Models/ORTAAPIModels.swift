//
//  ORTAAPIModels.swift
//  ORTA_APP
//

import Foundation
import CoreLocation

struct RoutesResponse: Decodable {
    let routes: [ORTARouteSummary]
}

struct ORTARouteSummary: Decodable, Identifiable {
    var id: String { slug }
    let slug: String
    let origin: String?
    let destination: String?
    let distanceKm: Double?
    let trucks: [ORTATruckOption]

    enum CodingKeys: String, CodingKey {
        case slug, origin, destination, trucks
        case distanceKm = "distance_km"
    }
}

struct ORTATruckOption: Decodable, Identifiable {
    var id: String { slug }
    let slug: String
    let label: String?
    let nTrips: Int?

    enum CodingKeys: String, CodingKey {
        case slug, label
        case nTrips = "n_trips"
    }
}

struct KPIsResponse: Decodable {
    let empty: Bool?
    let fuelLPer100km: Double?
    let nTrips: Int?

    enum CodingKeys: String, CodingKey {
        case empty
        case fuelLPer100km = "fuel_l_per_100km"
        case nTrips = "n_trips"
    }
}

struct CoachingResponse: Decodable {
    let empty: Bool?
    let originQuery: String?
    let destinationQuery: String?
    let totalDistanceKm: Double?
    let nSegments: Int?
    let legend: CoachingLegend?
    let segments: [CoachingSegment]
    let origin: MapEndpoint?
    let destination: MapEndpoint?

    enum CodingKeys: String, CodingKey {
        case empty
        case originQuery = "origin_query"
        case destinationQuery = "destination_query"
        case totalDistanceKm = "total_distance_km"
        case nSegments = "n_segments"
        case legend, segments, origin, destination
    }
}

struct CoachingLegend: Decodable {
    let label: String?
    let min: Double?
    let max: Double?
}

struct MapEndpoint: Decodable {
    let lat: Double
    let lon: Double
    let label: String?
}

struct CoachingSegment: Decodable, Identifiable {
    var id: Int { segIdx }

    let segIdx: Int
    let startLat: Double
    let startLon: Double
    let endLat: Double
    let endLon: Double
    let lengthM: Double
    let slopePct: Double
    let color: String?
    let weight: Double?
    let ambientTempC: Double?
    let windSpeedMs: Double?
    let precipMmph: Double?
    let speedKmh: Double?
    let rpm: Double?
    let recommendationAction: String?
    let recommendationMessage: String?
    let recommendationScience: String?
    let recommendationSavings: Double?
    let alerts: [String]?
    let showWeatherMarker: Bool?
    let congestionRatio: Double?

    enum CodingKeys: String, CodingKey {
        case segIdx = "seg_idx"
        case startLat = "start_lat"
        case startLon = "start_lon"
        case endLat = "end_lat"
        case endLon = "end_lon"
        case lengthM = "length_m"
        case slopePct = "slope_pct"
        case color, weight
        case ambientTempC = "ambient_temp_c"
        case windSpeedMs = "wind_speed_ms"
        case precipMmph = "precip_mmph"
        case speedKmh = "speed_kmh"
        case rpm
        case recommendationAction = "recommendation_action"
        case recommendationMessage = "recommendation_message"
        case recommendationScience = "recommendation_science"
        case recommendationSavings = "recommendation_savings"
        case alerts
        case showWeatherMarker = "show_weather_marker"
        case congestionRatio = "congestion_ratio"
    }

    var coordinatePair: [CLLocationCoordinate2D] {
        [
            CLLocationCoordinate2D(latitude: startLat, longitude: startLon),
            CLLocationCoordinate2D(latitude: endLat, longitude: endLon),
        ]
    }

    /// Texto UI sin la cola de torque (API antigua); el backend ya envía el mensaje corto.
    var recommendationMessageForDisplay: String {
        var m = (recommendationMessage ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = m.range(of: " para torque", options: .caseInsensitive) {
            m.removeSubrange(r.lowerBound..<m.endIndex)
        }
        return m.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Texto acotado para voz (TTS): como mucho dos frases; evita leer avisos enteros.
    var speechBriefForVoice: String {
        let m = recommendationMessageForDisplay.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !m.isEmpty else { return "" }
        let bits = m
            .components(separatedBy: ". ")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard let first = bits.first else { return "" }
        if bits.count >= 2 {
            var a = first
            if !a.hasSuffix(".") { a += "." }
            var b = bits[1]
            if b.count > 140 {
                b = String(b.prefix(137)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
            } else if !b.hasSuffix(".") && !b.hasSuffix("…") {
                b += "."
            }
            return "\(a) \(b)"
        }
        if first.count > 200 {
            return String(first.prefix(197)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
        }
        return first + (first.hasSuffix(".") || first.hasSuffix("…") ? "" : ".")
    }
}
