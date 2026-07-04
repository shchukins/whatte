import SwiftUI

struct DashboardCard<Content: View>: View {
    let title: String
    var accent: Color = HEColor.accentCyan
    var secondaryBackground: Bool = false
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Rectangle()
                    .fill(accent)
                    .frame(width: 10, height: 2)

                Text(title)
                    .font(HETypography.overline)
                    .foregroundStyle(HEColor.secondaryText)
                    .tracking(1.2)
                    .lineLimit(1)
                    .minimumScaleFactor(0.9)
            }

            content
        }
        .heCard(background: secondaryBackground ? HEColor.cardSecondary : HEColor.card)
    }
}

struct StatusBadge: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)

            Text(text)
                .font(HETypography.overline)
                .foregroundStyle(color)
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
        .overlay(
            Capsule()
                .stroke(color.opacity(0.35), lineWidth: 1)
        )
    }
}

struct MetricRow: View {
    let title: String
    let value: String
    var valueColor: Color = HEColor.primaryText

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(HETypography.overline)
                .foregroundStyle(HEColor.secondaryText)
                .tracking(1.0)
                .lineLimit(1)
                .minimumScaleFactor(0.8)

            Text(value)
                .font(HETypography.metric)
                .monospacedDigit()
                .foregroundStyle(valueColor)
                .lineLimit(2)
                .minimumScaleFactor(0.85)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SyncActionButton: View {
    let title: String
    let subtitle: String
    let icon: String
    let accent: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(accent)

                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(HETypography.overline)
                        .foregroundStyle(HEColor.primaryText)
                        .tracking(1.2)
                        .lineLimit(1)
                        .minimumScaleFactor(0.9)

                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(HEColor.secondaryText)
                        .lineLimit(2)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 100, alignment: .leading)
            .background(HEColor.cardSecondary)
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(accent.opacity(0.35), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }
}

struct DataSourceRow: View {
    let title: String
    let subtitle: String
    let status: String
    let color: Color

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(HETypography.metric)
                    .foregroundStyle(HEColor.primaryText)
                    .lineLimit(1)
                    .minimumScaleFactor(0.9)

                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(HEColor.secondaryText)
                    .lineLimit(2)
            }

            Spacer()

            StatusBadge(text: status, color: color)
        }
        .padding(.vertical, 2)
    }
}
