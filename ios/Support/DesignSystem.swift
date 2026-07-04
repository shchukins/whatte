import SwiftUI

enum HEColor {
    static let background = Color(red: 8 / 255, green: 15 / 255, blue: 18 / 255)
    static let card = Color(red: 15 / 255, green: 20 / 255, blue: 27 / 255)
    static let cardSecondary = Color(red: 18 / 255, green: 24 / 255, blue: 32 / 255)
    static let border = Color(red: 30 / 255, green: 39 / 255, blue: 51 / 255)
    static let primaryText = Color(red: 230 / 255, green: 240 / 255, blue: 1.0)
    static let secondaryText = Color(red: 138 / 255, green: 148 / 255, blue: 166 / 255)
    static let accentGreen = Color(red: 34 / 255, green: 1.0, blue: 148 / 255)
    static let accentCyan = Color(red: 0, green: 229 / 255, blue: 1.0)
    static let accentYellow = Color(red: 1.0, green: 217 / 255, blue: 74 / 255)
    static let accentPurple = Color(red: 154 / 255, green: 111 / 255, blue: 1.0)
    static let error = Color(red: 1.0, green: 96 / 255, blue: 122 / 255)
}

enum HETypography {
    static let overline = Font.system(size: 11, weight: .semibold, design: .monospaced)
    static let metric = Font.system(size: 15, weight: .semibold, design: .default)
    static let value = Font.system(size: 20, weight: .semibold, design: .default)
    static let hero = Font.system(size: 34, weight: .black, design: .default)
    static let title = Font.system(size: 18, weight: .bold, design: .default)
    static let body = Font.system(size: 15, weight: .regular, design: .default)
    static let status = Font.system(size: 30, weight: .bold, design: .default)
}

struct HECardModifier: ViewModifier {
    let background: Color

    func body(content: Content) -> some View {
        content
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(background)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(HEColor.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .shadow(color: HEColor.accentCyan.opacity(0.06), radius: 14, y: 4)
    }
}

extension View {
    func heCard(background: Color = HEColor.card) -> some View {
        modifier(HECardModifier(background: background))
    }
}
