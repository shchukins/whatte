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

    // MARK: - View

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    readinessCard
                    syncStatusView
                }
                .padding()
            }
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
                VStack(alignment: .leading, spacing: 20) {
                    heroSection(readiness)
                    recommendationSection(readiness)
                    trendSection
                    whySection(readiness)

                    recoveryBreakdownSection(readiness)

                    if readiness.explanation?.freshness == nil {
                        Text("Based only on recovery data")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    syncStatusView
                }
                .padding()
                .background(Color(.systemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(.separator), lineWidth: 1)
                )
            } else if let error = viewModel.readinessErrorMessage {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Today")
                        .font(.headline)

                    Text("Failed to load readiness")
                        .font(.subheadline)

                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding()
                .background(Color(.systemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(.separator), lineWidth: 1)
                )
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Today")
                        .font(.headline)

                    Text("No readiness data yet")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .padding()
                .background(Color(.systemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(.separator), lineWidth: 1)
                )
            }
        }
    }

    private var syncStatusView: some View {
        Text(syncStatusText)
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    private var trendSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("7-day trend")
                    .font(.subheadline)
                    .fontWeight(.semibold)

                Spacer()

                Text(readinessTrendLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if viewModel.readinessHistory.count < 2 {
                Text("Not enough history")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                HStack(alignment: .bottom, spacing: 8) {
                    ForEach(viewModel.readinessHistory) { item in
                        trendBar(item)
                    }
                }
            }
        }
    }

    private func heroSection(_ readiness: ReadinessDailyResponse) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Today")
                .font(.headline)
                .foregroundStyle(.secondary)

            HStack(alignment: .firstTextBaseline, spacing: 16) {
                Text(format(readiness.readinessScore))
                    .font(.system(size: 56, weight: .bold))
                    .foregroundStyle(readinessColor(readiness.readinessScore))

                VStack(alignment: .leading, spacing: 6) {
                    Text(readiness.statusText ?? "No status")
                        .font(.title3)
                        .fontWeight(.semibold)

                    Text("Good day probability \(formatPercent(readiness.goodDayProbability))")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func recommendationSection(_ readiness: ReadinessDailyResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recommendation")
                .font(.caption)
                .foregroundStyle(.secondary)

            Text(recommendationText(readiness: readiness.readinessScore))
                .font(.headline)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func whySection(_ readiness: ReadinessDailyResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Why")
                .font(.subheadline)
                .fontWeight(.semibold)

            HStack(spacing: 12) {
                metricTile(
                    title: "Freshness",
                    value: freshnessText(from: readiness.explanation?.freshness)
                )

                metricTile(
                    title: "Recovery",
                    value: format(readiness.explanation?.recoveryScoreSimple)
                )
            }

            if let explanationText = readinessExplanationText(for: readiness) {
                Text(explanationText)
                    .font(.subheadline)
                    .foregroundStyle(.primary)
                    .lineLimit(2)
            }
        }
    }

    @ViewBuilder
    private func recoveryBreakdownSection(_ readiness: ReadinessDailyResponse) -> some View {
        if let recovery = readiness.explanation?.recoveryExplanation {
            VStack(alignment: .leading, spacing: 12) {
                Text("Recovery breakdown")
                    .font(.subheadline)
                    .fontWeight(.semibold)

                scoreRow(title: "Sleep", score: recovery.sleepScore)
                scoreRow(title: "HRV", score: recovery.hrvScore)
                scoreRow(title: "Resting HR", score: recovery.rhrScore)
            }
        }
    }

    // MARK: - Reusable blocks

    @ViewBuilder
    private func metricTile(title: String, value: String) -> some View {
        VStack(spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)

            Text(value)
                .font(.headline)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func scoreRow(title: String, score: Double?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                    .font(.subheadline)

                Spacer()

                Text(format(score))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            ProgressView(value: (score ?? 0) / 100.0)
                .tint(readinessColor(score))
        }
    }

    @ViewBuilder
    private func trendBar(_ item: ReadinessHistoryItem) -> some View {
        let score = item.readinessScore ?? 0
        let height = max(8, CGFloat(score / 100.0) * 40.0)

        VStack(spacing: 6) {
            Text(shortScore(score))
                .font(.caption2)
                .foregroundStyle(.secondary)

            RoundedRectangle(cornerRadius: 4)
                .fill(readinessColor(item.readinessScore))
                .frame(width: 22, height: height)

            Text(shortDateLabel(item.date))
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Helpers

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

    private func shortDateLabel(_ dateString: String) -> String {
        let parts = dateString.split(separator: "-")
        return String(parts.last ?? "")
    }

    private var syncStatusText: String {
        if viewModel.syncState.lastErrorMessage != nil {
            return "Sync failed, will retry"
        }

        guard let lastSuccessfulSyncAt = viewModel.syncState.lastSuccessfulSyncAt else {
            return "No data yet"
        }

        return "Updated \(relativeTimeString(from: lastSuccessfulSyncAt))"
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
