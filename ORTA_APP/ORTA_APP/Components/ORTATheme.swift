//
//  ORTATheme.swift
//  ORTA_APP
//

import SwiftUI

enum ORTATheme {
    static let bg = Color(red: 0.06, green: 0.08, blue: 0.13)
    static let card = Color(red: 0.10, green: 0.12, blue: 0.18)
    static let accent = Color(red: 0.31, green: 0.63, blue: 1.0)
    static let textSecondary = Color(red: 0.55, green: 0.58, blue: 0.66)
}

extension Color {
    init(ortaHex: String) {
        var h = ortaHex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        if h.hasPrefix("#") { h.removeFirst() }
        var int: UInt64 = 0
        Scanner(string: h).scanHexInt64(&int)
        let r, g, b: UInt64
        switch h.count {
        case 6:
            (r, g, b) = (int >> 16, int >> 8 & 0xFF, int & 0xFF)
        default:
            (r, g, b) = (0x33, 0x88, 0xff)
        }
        self.init(.sRGB, red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255, opacity: 1)
    }
}
