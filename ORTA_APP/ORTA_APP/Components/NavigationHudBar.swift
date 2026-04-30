//
//  NavigationHudBar.swift
//  ORTA_APP
//

import SwiftUI

/// HUD compacto en dos filas: ruta (tiempo, km, tramo) y clima, sin scroll.
struct NavigationHudBar: View {
    private static let accent = Color(red: 0.45, green: 0.92, blue: 0.72)

    let etaMinutes: Int?
    let routeKm: Double?
    let segment: CoachingSegment?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 0) {
                chip(icon: "clock.fill", label: etaLabel)
                separator
                chip(icon: "map.fill", label: kmLabel)
                if let s = segment {
                    separator
                    chip(icon: "mappin.circle.fill", label: "Tramo \(s.segIdx)")
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let s = segment {
                HStack(spacing: 0) {
                    chip(
                        icon: "cloud.sun.fill",
                        label: String(format: "%.0f °C", s.ambientTempC ?? 0)
                    )
                    separator
                    chip(
                        icon: "wind",
                        label: String(format: "%.1f m/s", s.windSpeedMs ?? 0)
                    )
                    separator
                    chip(
                        icon: "cloud.rain.fill",
                        label: String(format: "%.1f mm/h", s.precipMmph ?? 0)
                    )
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.black.opacity(0.72))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(Color.white.opacity(0.12), lineWidth: 1)
                )
        )
    }

    private var etaLabel: String {
        guard let m = etaMinutes else { return "—" }
        return "~\(m) min"
    }

    private var kmLabel: String {
        guard let km = routeKm else { return "—" }
        if km >= 100 {
            return String(format: "%.0f km", km)
        }
        return String(format: "%.1f km", km)
    }

    private func chip(icon: String, label: String) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Self.accent)
                .frame(width: 16, alignment: .center)
            Text(label)
                .font(.system(size: 12, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
    }

    private var separator: some View {
        Text("·")
            .font(.system(size: 14, weight: .bold))
            .foregroundStyle(.white.opacity(0.32))
            .padding(.horizontal, 7)
            .baselineOffset(1)
    }
}

#Preview {
    VStack {
        NavigationHudBar(
            etaMinutes: 433,
            routeKm: 648.2,
            segment: nil
        )
        NavigationHudBar(
            etaMinutes: 42,
            routeKm: 18.8,
            segment: nil
        )
    }
    .padding()
    .background(Color.gray)
}
