//
//  CoachingMapView.swift
//  ORTA_APP
//

import MapKit
import SwiftUI

struct CoachingMapView: View {
    let segments: [CoachingSegment]
    let origin: MapEndpoint?
    let destination: MapEndpoint?
    @Binding var position: MapCameraPosition
    @Binding var selectedSegIdx: Int?

    @State private var mapLatitudeDelta: Double = 0.45

    private var allIncidents: [CoachingMapIncident] {
        CoachingIncidentScoring.incidents(from: segments)
    }

    private var visibleIncidents: [CoachingMapIncident] {
        CoachingIncidentScoring.visibleIncidents(all: allIncidents, latitudeDelta: mapLatitudeDelta)
    }

    private var routeOutline: [CLLocationCoordinate2D] {
        CoachingIncidentScoring.routeOutlineCoordinates(segments: segments)
    }

    private var visibleColoredSegments: [CoachingSegment] {
        CoachingIncidentScoring.visibleColoredSegments(segments, latitudeDelta: mapLatitudeDelta)
    }

    var body: some View {
        Map(position: $position, selection: $selectedSegIdx) {
            if routeOutline.count >= 2 {
                MapPolyline(coordinates: routeOutline)
                    .stroke(Color(red: 0.55, green: 0.82, blue: 1.0).opacity(0.55), lineWidth: 5)
                MapPolyline(coordinates: routeOutline)
                    .stroke(Color(red: 0.38, green: 0.68, blue: 0.98), lineWidth: 3)
            }
            ForEach(visibleColoredSegments) { seg in
                MapPolyline(coordinates: seg.coordinatePair)
                    .stroke(Color(ortaHex: seg.color ?? "#3388ff"), lineWidth: CGFloat(min(10, max(3, seg.weight ?? 4))))
                    .tag(seg.segIdx as Int?)
            }
            ForEach(visibleIncidents) { inc in
                Annotation(inc.tooltip, coordinate: inc.coordinate) {
                    incidentGlyph(inc.kind)
                }
            }
            if let o = origin {
                Annotation(o.label ?? "Origen", coordinate: CLLocationCoordinate2D(latitude: o.lat, longitude: o.lon)) {
                    ZStack {
                        Circle().fill(.green).frame(width: 14, height: 14)
                        Circle().stroke(.white, lineWidth: 2).frame(width: 14, height: 14)
                    }
                }
            }
            if let d = destination {
                Annotation(d.label ?? "Destino", coordinate: CLLocationCoordinate2D(latitude: d.lat, longitude: d.lon)) {
                    ZStack {
                        Circle().fill(.red).frame(width: 14, height: 14)
                        Circle().stroke(.white, lineWidth: 2).frame(width: 14, height: 14)
                    }
                }
            }
            UserAnnotation()
        }
        .mapStyle(.standard(elevation: .realistic))
        .mapControls {
            MapUserLocationButton()
            MapCompass()
        }
        .onMapCameraChange(frequency: .onEnd) { ctx in
            mapLatitudeDelta = ctx.region.span.latitudeDelta
        }
    }

    @ViewBuilder
    private func incidentGlyph(_ kind: CoachingMapIncidentKind) -> some View {
        switch kind {
        case .traffic:
            Circle()
                .fill(Color(red: 0.93, green: 0.27, blue: 0.27))
                .frame(width: 12, height: 12)
                .overlay(Circle().stroke(.white, lineWidth: 2))
        case .steepSlope:
            Circle()
                .fill(Color(red: 0.07, green: 0.09, blue: 0.15))
                .frame(width: 12, height: 12)
                .overlay(Circle().stroke(.white, lineWidth: 2))
        case .weather:
            Image(systemName: "cloud.sun.rain.fill")
                .font(.system(size: 16))
                .foregroundStyle(.cyan)
                .shadow(color: .black.opacity(0.35), radius: 1, y: 1)
        }
    }
}

enum MapBounds {
    static func camera(for segments: [CoachingSegment], padding: Double = 0.12) -> MapCameraPosition {
        let coords = segments.flatMap(\.coordinatePair)
        guard !coords.isEmpty else { return .automatic }
        var minLat = coords[0].latitude, maxLat = coords[0].latitude
        var minLon = coords[0].longitude, maxLon = coords[0].longitude
        for c in coords {
            minLat = min(minLat, c.latitude)
            maxLat = max(maxLat, c.latitude)
            minLon = min(minLon, c.longitude)
            maxLon = max(maxLon, c.longitude)
        }
        let center = CLLocationCoordinate2D(latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2)
        let spanLat = max((maxLat - minLat) * (1 + padding * 2), 0.02)
        let spanLon = max((maxLon - minLon) * (1 + padding * 2), 0.02)
        let region = MKCoordinateRegion(center: center, span: MKCoordinateSpan(latitudeDelta: spanLat, longitudeDelta: spanLon))
        return .region(region)
    }
}
