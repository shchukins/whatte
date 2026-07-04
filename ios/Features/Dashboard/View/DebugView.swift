import SwiftUI

struct DebugView: View {

    @State private var viewModel = DebugViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    actionsSection
                    permissionsSection
                    syncStateSection
                    payloadSummarySection
                    payloadPreviewSection
                    weightSection
                    restingHRSection
                    hrvSection
                    sleepSection
                }
                .padding()
            }
            .navigationTitle("Debug")
            .onAppear {
                viewModel.reloadSyncState()
                viewModel.refreshStatuses()
            }
        }
    }

    private var actionsSection: some View {
        GroupBox("Actions") {
            VStack(alignment: .leading, spacing: 10) {
                Text(viewModel.statusMessage)

                if viewModel.isSyncInProgress {
                    ProgressView("Sync in progress...")
                }

                Button("Request permissions") {
                    viewModel.requestPermissions()
                }

                Button("Refresh statuses") {
                    viewModel.refreshStatuses()
                }

                Button("Read sample data") {
                    viewModel.readSampleData()
                }

                Button("Build payload preview") {
                    viewModel.buildPayloadPreview()
                }

                Button("Reset sync state") {
                    viewModel.resetSyncState()
                }

                Button("Full sync") {
                    viewModel.performFullSync()
                }

                Button("Incremental sync") {
                    viewModel.performIncrementalSync()
                }

                Button("Backfill since May 23") {
                    viewModel.performBackfillSinceMay23()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var permissionsSection: some View {
        GroupBox("Permissions") {
            if viewModel.authorizationItems.isEmpty {
                Text("No statuses yet")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(viewModel.authorizationItems, id: \.name) { item in
                        HStack {
                            Text(item.name)
                            Spacer()
                            Text(item.status)
                                .foregroundStyle(.secondary)
                        }
                    }

                    Text("HealthKit read permissions are verified by data access, not authorizationStatus.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var syncStateSection: some View {
        GroupBox("Sync state") {
            VStack(alignment: .leading, spacing: 6) {
                Text("Last sync: \(viewModel.syncState.lastSuccessfulSyncAt.map(DateFormatters.shortDateTime) ?? "none")")
                Text("Last payload generated: \(viewModel.syncState.lastPayloadGeneratedAt.map(DateFormatters.shortDateTime) ?? "none")")
                Text("Last sent item count: \(viewModel.syncState.lastSentItemCount)")
                Text("Mode: \(viewModel.syncState.lastSyncMode?.rawValue ?? "none")")
                Text("Error: \(viewModel.syncState.lastErrorMessage ?? "none")")
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var payloadSummarySection: some View {
        GroupBox("Payload summary") {
            Text(viewModel.payloadSummary.isEmpty ? "No data" : viewModel.payloadSummary)
                .font(.system(.caption, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var payloadPreviewSection: some View {
        GroupBox("Payload preview") {
            ScrollView {
                Text(viewModel.payloadPreview.isEmpty ? "No preview" : viewModel.payloadPreview)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 280)
        }
    }

    private var weightSection: some View {
        GroupBox("Weight") {
            if viewModel.weightSamples.isEmpty {
                Text("No samples")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(viewModel.weightSamples) { sample in
                        Text("\(sample.kilograms, specifier: "%.1f") kg")
                    }
                }
            }
        }
    }

    private var restingHRSection: some View {
        GroupBox("Resting HR") {
            if viewModel.restingHRSamples.isEmpty {
                Text("No samples")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(viewModel.restingHRSamples) { sample in
                        Text("\(sample.bpm, specifier: "%.1f") bpm")
                    }
                }
            }
        }
    }

    private var hrvSection: some View {
        GroupBox("HRV") {
            if viewModel.hrvSamples.isEmpty {
                Text("No samples")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(viewModel.hrvSamples) { sample in
                        Text("\(sample.milliseconds, specifier: "%.1f") ms")
                    }
                }
            }
        }
    }

    private var sleepSection: some View {
        GroupBox("Sleep nights") {
            if viewModel.sleepNightAggregates.isEmpty {
                Text("No nights")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(viewModel.sleepNightAggregates.enumerated()), id: \.offset) { _, night in
                        Text("\(night.totalSleepMinutes, specifier: "%.1f") min")
                    }
                }
            }
        }
    }
}
