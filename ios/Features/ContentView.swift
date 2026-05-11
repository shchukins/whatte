//
//  ContentView.swift
//  HumanEngineIOS
//
//  Created by Сергей Щукин on 05.04.2026.
//

import SwiftUI

struct ContentView: View {

    // MARK: - UI state

    @State private var viewModel = ContentViewModel()
    private let terminalLabelFont = Font.system(size: 12, weight: .medium, design: .monospaced)
    private let terminalRowFont = Font.system(size: 18, weight: .regular, design: .monospaced)
    private let terminalValueFont = Font.system(size: 18, weight: .semibold, design: .monospaced)
    private let mainBriefingFont = Font.system(size: 26, weight: .bold, design: .default)
    private let scoreFont = Font.system(size: 64, weight: .black, design: .rounded)
    private let bodyLabelFont = Font.system(size: 17, weight: .regular, design: .default)

    // MARK: - View

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    readinessCard
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Today")
            .onAppear {
                viewModel.reloadSyncState()
                viewModel.loadTodayReadiness()
                viewModel.loadReadinessHistory()
            }
            .onReceive(NotificationCenter.default.publisher(for: .syncStateDidChange)) { _ in
                viewModel.reloadSyncState()
            }
            .onReceive(NotificationCenter.default.publisher(for: .autoSyncDidFinish)) { _ in
                viewModel.reloadSyncState()
                viewModel.loadTodayReadiness()
                viewModel.loadReadinessHistory()
            }
        }
    }

    // MARK: - Main screen

    private var readinessCard: some View {
        Group {
            if let readiness = viewModel.todayReadiness {
                VStack(alignment: .leading, spacing: 12) {
                    mainStatusPanel(readiness)
                    recommendationPanel(readiness)
                    trendPanel
                    signalsPanel(readiness)
                    dataQualityPanel(readiness)
                    recoveryPanel(readiness)
                    footerView
                }
            } else if let error = viewModel.readinessErrorMessage {
                terminalPanel {
                    VStack(alignment: .leading, spacing: 8) {
                        sectionLabel("STATUS")

                        Text("Failed to load readiness")
                            .font(.headline)

                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                terminalPanel {
                    VStack(alignment: .leading, spacing: 8) {
                        sectionLabel("STATUS")

                        Text("No readiness data yet")
                            .font(.headline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var syncStatusView: some View {
        Text(syncStatusText)
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private var footerView: some View {
        HStack {
            syncStatusView
            Spacer()
        }
        .padding(.horizontal, 4)
    }

    private func mainStatusPanel(_ readiness: ReadinessDailyResponse) -> some View {
        terminalPanel {
            VStack(alignment: .leading, spacing: 12) {
                sectionLabel("STATUS")

                if let briefingText = mainBriefingText(for: readiness) {
                    Text(briefingText)
                        .font(mainBriefingFont)
                        .foregroundStyle(.primary)
                        .lineSpacing(3)
                }

                HStack(alignment: .bottom, spacing: 16) {
                    Text(format(readiness.readinessScore))
                        .font(scoreFont)
                        .foregroundStyle(readinessColor(readiness.readinessScore))

                    VStack(alignment: .leading, spacing: 4) {
                        if let secondaryStatusText = secondaryStatusText(for: readiness) {
                            Text(secondaryStatusText)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }

                        Text("Prob: \(formatPercent(readiness.goodDayProbability))")
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func recommendationPanel(_ readiness: ReadinessDailyResponse) -> some View {
        terminalPanel {
            VStack(alignment: .leading, spacing: 6) {
                sectionLabel("RECOMMENDATION")

                Text(recommendationLabel(from: readiness.recommendation) ?? recommendationText(readiness: readiness.readinessScore))
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
            }
        }
    }

    private var trendPanel: some View {
        terminalPanel {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    sectionLabel("TREND")
                    Spacer()
                    Text(readinessTrendLabel)
                        .font(terminalLabelFont)
                        .foregroundStyle(.secondary)
                }

                if viewModel.readinessHistory.count < 2 {
                    Text("Not enough history")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    VStack(spacing: 6) {
                        HStack(spacing: 8) {
                            ForEach(viewModel.readinessHistory) { item in
                                Text(shortDateLabel(item.date))
                                    .font(terminalLabelFont)
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity)
                            }
                        }

                        HStack(spacing: 8) {
                            ForEach(viewModel.readinessHistory) { item in
                                trendBar(item)
                            }
                        }

                        HStack(spacing: 8) {
                            ForEach(viewModel.readinessHistory) { item in
                                Text(shortScore(item.readinessScore ?? 0))
                                    .font(terminalLabelFont)
                                    .monospacedDigit()
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity)
                            }
                        }
                    }
                }
            }
        }
    }

    private func signalsPanel(_ readiness: ReadinessDailyResponse) -> some View {
        terminalPanel {
            VStack(alignment: .leading, spacing: 10) {
                sectionLabel("SIGNALS")

                compactValueRow(title: "Freshness", value: freshnessText(from: readiness.explanation?.freshness))
                compactValueRow(title: "Recovery", value: format(readiness.explanation?.recoveryScoreSimple))
            }
        }
    }

    @ViewBuilder
    private func dataQualityPanel(_ readiness: ReadinessDailyResponse) -> some View {
        if let dataQuality = readiness.dataQuality {
            terminalPanel {
                VStack(alignment: .leading, spacing: 10) {
                    sectionLabel("DATA")

                    dataQualityRow(title: "Sleep", value: dataQuality.sleep)
                    dataQualityRow(title: "HRV", value: dataQuality.hrv)
                    dataQualityRow(title: "Rest HR", value: dataQuality.restingHR)
                    dataQualityRow(title: "Training", value: dataQuality.training)
                }
            }
        }
    }

    private func recoveryPanel(_ readiness: ReadinessDailyResponse) -> some View {
        terminalPanel {
            recoveryBreakdownSection(readiness)
        }
    }

    @ViewBuilder
    private func recoveryBreakdownSection(_ readiness: ReadinessDailyResponse) -> some View {
        if let recovery = readiness.explanation?.recoveryExplanation {
            VStack(alignment: .leading, spacing: 10) {
                sectionLabel("RECOVERY")

                recoveryRow(title: "Sleep", score: recovery.sleepScore)
                recoveryRow(title: "HRV", score: recovery.hrvScore)
                recoveryRow(title: "Resting HR", score: recovery.rhrScore)
            }
        }
    }

    // MARK: - Reusable blocks

    @ViewBuilder
    private func compactValueRow(title: String, value: String) -> some View {
        HStack(spacing: 12) {
            Text(title)
                .font(bodyLabelFont)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(width: 110, alignment: .leading)

            Spacer(minLength: 0)

            Text(value)
                .font(terminalValueFont)
                .monospacedDigit()
                .foregroundStyle(.primary)
            .lineLimit(1)
        }
    }

    @ViewBuilder
    private func dataQualityRow(title: String, value: String?) -> some View {
        HStack(spacing: 12) {
            Text(title)
                .font(bodyLabelFont)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(width: 110, alignment: .leading)

            Spacer(minLength: 0)

            Text(dataQualityLabel(value))
                .font(terminalValueFont)
                .foregroundStyle(dataQualityColor(value))
                .lineLimit(1)
        }
    }

    @ViewBuilder
    private func trendBar(_ item: ReadinessHistoryItem) -> some View {
        let scores = viewModel.readinessHistory.map { $0.readinessScore ?? 0 }
        let score = item.readinessScore ?? 0
        let minScore = scores.min() ?? 0
        let maxScore = scores.max() ?? 100
        let height = relativeTrendHeight(score: score, minScore: minScore, maxScore: maxScore)

        VStack(spacing: 0) {
            RoundedRectangle(cornerRadius: 2)
                .fill(readinessColor(item.readinessScore))
                .frame(width: 16, height: height)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
    }

    @ViewBuilder
    private func recoveryRow(title: String, score: Double?) -> some View {
        HStack(spacing: 10) {
            Text(title)
                .font(bodyLabelFont)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .frame(width: 110, alignment: .leading)

            Text(format(score))
                .font(.system(size: 17, weight: .semibold, design: .monospaced))
                .monospacedDigit()
                .foregroundStyle(.primary)
                .frame(width: 48, alignment: .trailing)

            Text(terminalBar(value: score))
                .font(.system(size: 17, weight: .regular, design: .monospaced))
                .foregroundStyle(readinessColor(score))
                .lineLimit(1)

            Spacer(minLength: 0)
        }
    }

    // MARK: - Helpers

    private func terminalPanel<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color.white.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
    }

    private func sectionLabel(_ text: String) -> some View {
        Text("> \(text)")
            .font(terminalLabelFont)
            .textCase(.uppercase)
            .foregroundStyle(.secondary)
    }

    private func format(_ value: Double?) -> String {
        guard let value else { return "n/a" }
        return String(format: "%.1f", value)
    }

    private func formatPercent(_ value: Double?) -> String {
        guard let value else { return "n/a" }
        return String(format: "%.1f%%", value * 100.0)
    }

    private func freshnessText(from value: Double?) -> String {
        guard let value else { return "No load data" }
        return String(format: "%.1f", value)
    }

    private func dataQualityLabel(_ value: String?) -> String {
        guard let value = trimmedText(value) else { return "n/a" }

        switch value.lowercased() {
        case "ok":
            return "OK"
        case "partial":
            return "Partial"
        case "missing":
            return "Missing"
        default:
            return value
        }
    }

    private func dataQualityColor(_ value: String?) -> Color {
        switch trimmedText(value)?.lowercased() {
        case "ok":
            return .green
        case "partial":
            return .yellow
        case "missing":
            return .secondary
        default:
            return .primary
        }
    }

    private func readinessExplanationText(for readiness: ReadinessDailyResponse) -> String? {
        if let readinessComment = trimmedText(readiness.readinessComment) {
            return readinessComment
        }

        if let briefingText = trimmedText(readiness.briefingText) {
            return briefingText
        }

        if let statusText = trimmedText(readiness.statusText) {
            return statusText
        }

        if readiness.readinessScore != nil || readiness.explanation != nil {
            return "Not enough data yet"
        }

        return nil
    }

    private func trimmedText(_ text: String?) -> String? {
        guard let text else { return nil }

        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func mainBriefingText(for readiness: ReadinessDailyResponse) -> String? {
        if let briefing = trimmedText(readiness.briefing) {
            return briefing
        }

        if let briefingText = trimmedText(readiness.briefingText) {
            return briefingText
        }

        return nil
    }

    private func secondaryStatusText(for readiness: ReadinessDailyResponse) -> String? {
        let statusText = trimmedText(readiness.statusText)

        return statusText
    }

    private func recommendationText(for readiness: ReadinessDailyResponse) -> String {
        if let recommendation = trimmedText(readiness.recommendation) {
            return recommendation
        }

        return recommendationText(readiness: readiness.readinessScore)
    }

    private func recommendationLabel(from value: String?) -> String? {
        guard let value = trimmedText(value)?.lowercased() else { return nil }

        switch value {
        case "recovery":
            return "Recovery day"
        case "endurance":
            return "Easy endurance"
        case "moderate":
            return "Moderate training"
        case "high_intensity":
            return "High intensity possible"
        default:
            return nil
        }
    }

    private func recommendationText(readiness: Double?) -> String {
        guard let readiness else { return "Not enough data" }

        switch readiness {
        case ..<40:
            return "Recovery or rest day"
        case 40...60:
            return "Easy training recommended"
        case 60...75:
            return "Good day for endurance"
        default:
            return "Good day for hard workout"
        }
    }

    private var readinessTrendLabel: String {
        let scores = viewModel.readinessHistory.compactMap(\.readinessScore)

        guard viewModel.readinessHistory.count >= 2, let first = scores.first, let last = scores.last else {
            return "Not enough history"
        }

        if last - first >= 5 {
            return "Improving"
        }

        if first - last >= 5 {
            return "Declining"
        }

        return "Stable"
    }

    private func shortScore(_ score: Double) -> String {
        String(format: "%.0f", score)
    }

    private func terminalBar(value: Double?) -> String {
        guard let value else { return "░░░░░░░░░░" }

        let filled = max(0, min(10, Int(value / 10.0)))
        return String(repeating: "█", count: filled) + String(repeating: "░", count: 10 - filled)
    }

    private func relativeTrendHeight(score: Double, minScore: Double, maxScore: Double) -> CGFloat {
        let minHeight: CGFloat = 8
        let maxHeight: CGFloat = 34
        let range = max(maxScore - minScore, 1)
        let normalized = (score - minScore) / range
        return minHeight + CGFloat(normalized) * (maxHeight - minHeight)
    }

    private func shortDateLabel(_ dateString: String) -> String {
        let parts = dateString.split(separator: "-")
        return String(parts.last ?? "")
    }

    private var syncStatusText: String {
        if viewModel.syncState.lastErrorMessage != nil {
            return "Sync failed, will retry"
        }

        if let lastSuccessfulSyncAt = viewModel.syncState.lastSuccessfulSyncAt {
            return "Updated \(relativeTimeString(from: lastSuccessfulSyncAt))"
        }

        if let lastSyncAttemptAt = viewModel.syncState.lastSyncAttemptAt {
            return "Checked \(relativeTimeString(from: lastSyncAttemptAt))"
        }

        return "No data yet"
    }

    private func relativeTimeString(from date: Date) -> String {
        let seconds = Int(Date().timeIntervalSince(date))

        if seconds < 60 {
            return "just now"
        }

        let minutes = seconds / 60
        if minutes < 60 {
            return minutes == 1 ? "1 min ago" : "\(minutes) min ago"
        }

        let hours = minutes / 60
        if hours < 24 {
            return hours == 1 ? "1 h ago" : "\(hours) h ago"
        }

        return DateFormatters.shortDateTime(date)
    }

    private func readinessColor(_ score: Double?) -> Color {
        guard let score else { return .gray }

        switch score {
        case ..<40:
            return .red
        case 40..<60:
            return .orange
        case 60..<75:
            return .yellow
        default:
            return .green
        }
    }
}

#Preview {
    ContentView()
}
