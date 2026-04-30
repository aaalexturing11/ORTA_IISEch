//
//  CoachBottomCard.swift
//  ORTA_APP
//

import SwiftUI

struct CoachBottomCard: View {
    let segment: CoachingSegment?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let s = segment {
                Text("Segmento \(s.segIdx)")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(ORTATheme.accent)
                Text(s.recommendationMessage ?? "—")
                    .font(.body)
                    .foregroundStyle(.primary)
                if (s.recommendationAction ?? "KEEP") != "KEEP", let sci = s.recommendationScience {
                    Text(sci)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Label(String(format: "%.1f°C", s.ambientTempC ?? 0), systemImage: "cloud.sun")
                    Spacer()
                    Label(String(format: "%.1f m/s", s.windSpeedMs ?? 0), systemImage: "wind")
                    Spacer()
                    Label(String(format: "%.1f mm/h", s.precipMmph ?? 0), systemImage: "cloud.rain")
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            } else {
                Text("Toca un tramo del mapa para ver pendiente, clima y recomendación.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
    }
}

#Preview {
    CoachBottomCard(segment: nil)
        .padding()
}
