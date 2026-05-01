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
            }
            .onReceive(NotificationCenter.default.publisher(for: .syncStateDidChange)) { _ in
                viewModel.reloadSyncState()
            }
            .onReceive(NotificationCenter.default.publisher(for: .autoSyncDidFinish)) { _ in
                viewModel.reloadSyncState()
                viewModel.loadTodayReadiness()
            }
        }
    }

    // MARK: - Main screen

    private var readinessCard: some View {
        Group {
            if let readiness = viewModel.todayReadiness {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Today")
                                .font(.headline)

                            Text(readiness.statusText ?? "No status")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Text(format(readiness.readinessScore))
                            .font(.system(size: 48, weight: .bold))
                            .foregroundStyle(readinessColor(readiness.readinessScore))
                    }

                    Text("Good day probability \(formatPercent(readiness.goodDayProbability))")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

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

                    if readiness.explanation?.freshness == nil {
                        Text("Based only on recovery data")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
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
