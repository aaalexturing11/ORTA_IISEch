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

    var body: some View {
        Map(position: $position, selection: $selectedSegIdx) {
            ForEach(segments) { seg in
                MapPolyline(coordinates: seg.coordinatePair)
                    .stroke(Color(ortaHex: seg.color ?? "#3388ff"), lineWidth: CGFloat(min(10, max(3, seg.weight ?? 4))))
                    .tag(seg.segIdx as Int?)
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
