import SwiftUI

struct ContentView: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var viewModel = ContentViewModel()

    private let actionColumns = [
        GridItem(.flexible(), spacing: 12),
        GridItem(.flexible(), spacing: 12)
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                HEColor.background
                    .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        topBar
                        connectionStatusRow
                        if viewModel.requiresHealthKitAuthorization {
                            healthKitAccessCard
                        }
                        recoverySignalsCard
                        dataFreshnessCard
                        backendOwnershipCard
                        syncDataCard
                        dataSourcesCard
                        tabBar
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 28)
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .onAppear {
                viewModel.prepareDashboardForDisplay {
                    if scenePhase == .active {
                        viewModel.triggerAutoSync(reason: "app_open")
                    }
                }
            }
            .onChange(of: scenePhase) { _, newPhase in
                guard newPhase == .active else { return }
                viewModel.triggerAutoSync(reason: "app_active")
            }
            .onReceive(NotificationCenter.default.publisher(for: .syncStateDidChange)) { _ in
                viewModel.reloadSyncState()
                viewModel.refreshStatuses()
            }
            .onReceive(NotificationCenter.default.publisher(for: .autoSyncDidFinish)) { _ in
                viewModel.reloadSyncState()
                viewModel.refreshStatuses()
            }
        }
    }

    private var topBar: some View {
        HStack(spacing: 14) {
            Text(">_")
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .foregroundStyle(HEColor.accentGreen)

            VStack(alignment: .leading, spacing: 3) {
                Text("HUMAN ENGINE")
                    .font(.system(size: 22, weight: .bold, design: .default))
                    .foregroundStyle(HEColor.accentGreen)
                    .lineLimit(1)

                Text("HEALTHKIT INGESTION CLIENT")
                    .font(HETypography.overline)
                    .foregroundStyle(HEColor.secondaryText)
                    .tracking(1.2)
                    .lineLimit(1)
                    .minimumScaleFactor(0.9)
            }

            Spacer()

            Image(systemName: "gearshape")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(HEColor.secondaryText)
                .padding(10)
                .background(HEColor.card)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(HEColor.border, lineWidth: 1)
                )
        }
    }

    private var connectionStatusRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                StatusBadge(
                    text: viewModel.backendStatusLabel,
                    color: viewModel.backendStatusLabel == "CONNECTED" ? HEColor.accentGreen : HEColor.accentCyan
                )

                StatusBadge(text: "AUTO SYNC ON", color: HEColor.accentCyan)

                StatusBadge(text: "UPDATED \(updatedStatusText)", color: HEColor.accentYellow)
            }
        }
    }

    private var healthKitAccessCard: some View {
        DashboardCard(title: "HEALTHKIT ACCESS REQUIRED", accent: HEColor.accentYellow) {
            VStack(alignment: .leading, spacing: 14) {
                Text("HealthKit permissions required")
                    .font(HETypography.title)
                    .foregroundStyle(HEColor.primaryText)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Enable Sleep, HRV, Resting HR, and Weight access before sync can start.")
                    .font(HETypography.body)
                    .foregroundStyle(HEColor.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)

                Button("Enable HealthKit") {
                    viewModel.requestPermissions()
                }
                .buttonStyle(.borderedProminent)
                .tint(HEColor.accentGreen)
            }
        }
    }

    private var recoverySignalsCard: some View {
        DashboardCard(title: "RECOVERY SIGNALS", accent: HEColor.accentCyan) {
            VStack(alignment: .leading, spacing: 16) {
                Text("Latest HealthKit data")
                    .font(HETypography.body)
                    .foregroundStyle(HEColor.secondaryText)

                LazyVGrid(columns: actionColumns, alignment: .leading, spacing: 14) {
                    recoverySignalMetric(
                        title: "SLEEP",
                        value: viewModel.latestSleepValue,
                        color: HEColor.accentGreen
                    )
                    recoverySignalMetric(
                        title: "HRV",
                        value: viewModel.latestHRVValue,
                        color: HEColor.accentCyan
                    )
                    recoverySignalMetric(
                        title: "RESTING HR",
                        value: viewModel.latestRestingHRValue,
                        color: HEColor.accentYellow
                    )
                    recoverySignalMetric(
                        title: "WEIGHT",
                        value: viewModel.latestWeightValue,
                        color: HEColor.primaryText
                    )
                }
            }
        }
    }

    private var dataFreshnessCard: some View {
        DashboardCard(title: "DATA FRESHNESS", accent: HEColor.accentGreen, secondaryBackground: true) {
            VStack(alignment: .leading, spacing: 14) {
                ViewThatFits {
                    HStack(alignment: .top, spacing: 12) {
                        freshnessMetric(title: "LAST SYNC", value: viewModel.lastSyncDisplayText)
                        freshnessMetric(
                            title: "SYNC MODE",
                            value: viewModel.lastSyncModeDisplayText,
                            valueColor: accentColor(forMode: viewModel.syncState.lastSyncMode)
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        freshnessMetric(title: "LAST SYNC", value: viewModel.lastSyncDisplayText)
                        freshnessMetric(
                            title: "SYNC MODE",
                            value: viewModel.lastSyncModeDisplayText,
                            valueColor: accentColor(forMode: viewModel.syncState.lastSyncMode)
                        )
                    }
                }

                ViewThatFits {
                    HStack(alignment: .top, spacing: 12) {
                        freshnessMetric(title: "ITEMS SENT", value: "\(viewModel.syncState.lastSentItemCount)")
                        freshnessMetric(
                            title: "BACKEND",
                            value: viewModel.backendStatusLabel,
                            valueColor: color(forStatusKey: viewModel.backendStatusColor)
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        freshnessMetric(title: "ITEMS SENT", value: "\(viewModel.syncState.lastSentItemCount)")
                        freshnessMetric(
                            title: "BACKEND",
                            value: viewModel.backendStatusLabel,
                            valueColor: color(forStatusKey: viewModel.backendStatusColor)
                        )
                    }
                }

                if let error = viewModel.syncState.lastErrorMessage, !error.isEmpty {
                    Divider()
                        .overlay(HEColor.border)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("LAST ERROR")
                            .font(HETypography.overline)
                            .foregroundStyle(HEColor.error)
                            .tracking(1.0)

                        Text(error)
                            .font(.caption)
                            .foregroundStyle(HEColor.secondaryText)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private var backendOwnershipCard: some View {
        DashboardCard(title: "BACKEND OWNED", accent: HEColor.accentYellow, secondaryBackground: true) {
            Text("Load, readiness, recommendations, and Strava-based analytics are calculated on the backend.")
                .font(HETypography.body)
                .foregroundStyle(HEColor.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var syncDataCard: some View {
        DashboardCard(title: "SYNC & DATA", accent: HEColor.accentGreen) {
            VStack(alignment: .leading, spacing: 16) {
                LazyVGrid(columns: actionColumns, spacing: 12) {
                    SyncActionButton(
                        title: "SYNC NOW",
                        subtitle: "Full sync",
                        icon: "arrow.clockwise",
                        accent: HEColor.accentGreen
                    ) {
                        viewModel.runFullSyncFromMainScreen()
                    }

                    SyncActionButton(
                        title: "INCREMENTAL",
                        subtitle: "New data only",
                        icon: "arrow.down.circle",
                        accent: HEColor.accentCyan
                    ) {
                        viewModel.runIncrementalSyncFromMainScreen()
                    }

                    SyncActionButton(
                        title: "PAYLOAD",
                        subtitle: "View summary",
                        icon: "doc.text",
                        accent: HEColor.accentYellow
                    ) {
                        viewModel.buildPayloadPreview()
                    }
                }
                .disabled(viewModel.isSyncInProgress)

                if viewModel.isSyncInProgress {
                    ProgressView("Sync in progress...")
                        .tint(HEColor.accentGreen)
                        .foregroundStyle(HEColor.secondaryText)
                }

                VStack(alignment: .leading, spacing: 8) {
                    ViewThatFits {
                        HStack(alignment: .top, spacing: 12) {
                            MetricRow(title: "LAST SYNC", value: viewModel.lastSyncDisplayText)
                            MetricRow(title: "MODE", value: viewModel.lastSyncModeDisplayText, valueColor: accentColor(forMode: viewModel.syncState.lastSyncMode))
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            MetricRow(title: "LAST SYNC", value: viewModel.lastSyncDisplayText)
                            MetricRow(title: "MODE", value: viewModel.lastSyncModeDisplayText, valueColor: accentColor(forMode: viewModel.syncState.lastSyncMode))
                        }
                    }

                    ViewThatFits {
                        HStack(alignment: .top, spacing: 12) {
                            MetricRow(title: "ITEMS SENT", value: "\(viewModel.syncState.lastSentItemCount)")
                            MetricRow(title: "LAST PAYLOAD", value: viewModel.lastPayloadDisplayText)
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            MetricRow(title: "ITEMS SENT", value: "\(viewModel.syncState.lastSentItemCount)")
                            MetricRow(title: "LAST PAYLOAD", value: viewModel.lastPayloadDisplayText)
                        }
                    }
                }

                if !viewModel.payloadSummary.isEmpty {
                    Divider()
                        .overlay(HEColor.border)

                    Text(viewModel.payloadSummary)
                        .font(HETypography.metric)
                        .foregroundStyle(HEColor.secondaryText)
                        .textSelection(.enabled)
                }

                DisclosureGroup("UTILITY ACTIONS") {
                    VStack(alignment: .leading, spacing: 10) {
                        utilityButtonRow(
                            title: "REQUEST PERMISSIONS",
                            subtitle: "HealthKit authorization",
                            action: viewModel.requestPermissions
                        )

                        utilityButtonRow(
                            title: "REFRESH PERMISSIONS",
                            subtitle: "Reload authorization state",
                            action: viewModel.refreshStatuses
                        )

                        utilityButtonRow(
                            title: "READ SAMPLE DATA",
                            subtitle: "Load recent HealthKit samples",
                            action: viewModel.readSampleData
                        )

                        utilityButtonRow(
                            title: "RESET SYNC STATE",
                            subtitle: "Clear local sync metadata",
                            action: viewModel.resetSyncState
                        )
                    }
                    .padding(.top, 12)
                }
                .font(HETypography.overline)
                .tint(HEColor.secondaryText)

                if !viewModel.payloadPreview.isEmpty {
                    DisclosureGroup("PAYLOAD PREVIEW") {
                        Text(viewModel.payloadPreview)
                            .font(.system(size: 11, weight: .regular, design: .monospaced))
                            .foregroundStyle(HEColor.secondaryText)
                            .textSelection(.enabled)
                            .padding(.top, 10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .font(HETypography.overline)
                    .tint(HEColor.secondaryText)
                }
            }
        }
    }

    private var dataSourcesCard: some View {
        DashboardCard(title: "DATA SOURCES", accent: HEColor.accentCyan) {
            VStack(alignment: .leading, spacing: 14) {
                DataSourceRow(
                    title: "HealthKit",
                    subtitle: "Sleep, HRV, Resting HR, Weight",
                    status: viewModel.healthKitStatusLabel,
                    color: color(forStatusKey: viewModel.healthKitStatusColor)
                )

                Divider()
                    .overlay(HEColor.border)

                DataSourceRow(
                    title: "Strava",
                    subtitle: "Activities, Training Load",
                    status: "BACKEND",
                    color: HEColor.accentYellow
                )

                Divider()
                    .overlay(HEColor.border)

                DataSourceRow(
                    title: "Backend",
                    subtitle: viewModel.backendDisplayName,
                    status: viewModel.backendStatusLabel,
                    color: color(forStatusKey: viewModel.backendStatusColor)
                )

                Divider()
                    .overlay(HEColor.border)

                DataSourceRow(
                    title: "Manual / Debug",
                    subtitle: "Backfill, payload preview, reset",
                    status: "OK",
                    color: HEColor.accentPurple
                )

                Divider()
                    .overlay(HEColor.border)

                VStack(alignment: .leading, spacing: 8) {
                    Text("PERMISSIONS")
                        .font(HETypography.overline)
                        .foregroundStyle(HEColor.secondaryText)
                        .tracking(1.0)

                    ForEach(viewModel.authorizationItems, id: \.name) { item in
                        HStack {
                            Text(item.name.uppercased())
                                .font(HETypography.metric)
                                .foregroundStyle(HEColor.primaryText)
                                .lineLimit(1)
                                .minimumScaleFactor(0.9)

                            Spacer()

                            Text(item.status.uppercased())
                                .font(HETypography.overline)
                                .foregroundStyle(permissionColor(for: item.status))
                                .lineLimit(2)
                                .multilineTextAlignment(.trailing)
                        }
                    }

                    Text("HealthKit read permissions are verified by data access, not authorizationStatus.")
                        .font(.caption2)
                        .foregroundStyle(HEColor.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var tabBar: some View {
        HStack(spacing: 8) {
            dashboardTab("OVERVIEW", active: true)
            dashboardTab("SYNC", active: false)
            dashboardTab("RECOVERY", active: false)
            dashboardTab("TRENDS", active: false)
            dashboardTab("SETTINGS", active: false)
        }
        .padding(6)
        .frame(maxWidth: .infinity)
        .background(HEColor.card)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(HEColor.border, lineWidth: 1)
        )
    }

    private func utilityButtonRow(title: String, subtitle: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(HETypography.overline)
                        .foregroundStyle(HEColor.primaryText)
                        .tracking(1.0)
                        .lineLimit(1)

                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(HEColor.secondaryText)
                        .lineLimit(2)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(HEColor.secondaryText)
            }
            .padding(.vertical, 6)
        }
        .buttonStyle(.plain)
    }

    private func dashboardTab(_ title: String, active: Bool) -> some View {
        Text(title)
            .font(HETypography.overline)
            .foregroundStyle(active ? HEColor.background : HEColor.secondaryText)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(active ? HEColor.accentGreen : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .lineLimit(1)
            .minimumScaleFactor(0.75)
    }

    private func recoverySignalMetric(title: String, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(HETypography.overline)
                .foregroundStyle(HEColor.secondaryText)
                .tracking(1.0)
                .lineLimit(1)

            Text(value)
                .font(.system(size: 26, weight: .semibold, design: .default))
                .monospacedDigit()
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(HEColor.cardSecondary)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(HEColor.border, lineWidth: 1)
        )
    }

    private func freshnessMetric(title: String, value: String, valueColor: Color = HEColor.primaryText) -> some View {
        MetricRow(title: title, value: value, valueColor: valueColor)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func color(forStatusKey key: String) -> Color {
        switch key {
        case "connected":
            return HEColor.accentGreen
        case "warning":
            return HEColor.accentYellow
        case "error":
            return HEColor.error
        default:
            return HEColor.accentCyan
        }
    }

    private func accentColor(forMode mode: SyncMode?) -> Color {
        switch mode {
        case .full:
            return HEColor.accentGreen
        case .incremental:
            return HEColor.accentCyan
        case .backfill:
            return HEColor.accentPurple
        case nil:
            return HEColor.secondaryText
        }
    }

    private func permissionColor(for status: String) -> Color {
        switch status {
        case "READ OK":
            return HEColor.accentGreen
        case "NO DATA / CHECK HEALTH SETTINGS":
            return HEColor.accentYellow
        case "NOT REQUESTED":
            return HEColor.secondaryText
        default:
            return HEColor.error
        }
    }

    private var updatedStatusText: String {
        if let lastSuccessfulSyncAt = viewModel.syncState.lastSuccessfulSyncAt {
            return relativeTimeString(from: lastSuccessfulSyncAt).uppercased()
        }

        if let lastSyncAttemptAt = viewModel.syncState.lastSyncAttemptAt {
            return DateFormatters.shortDateTime(lastSyncAttemptAt).uppercased()
        }

        return "NOT YET"
    }

    private func relativeTimeString(from date: Date) -> String {
        let seconds = Int(Date().timeIntervalSince(date))

        if seconds < 60 {
            return "JUST NOW"
        }

        let minutes = seconds / 60
        if minutes < 60 {
            return minutes == 1 ? "1 MIN AGO" : "\(minutes) MIN AGO"
        }

        let hours = minutes / 60
        if hours < 24 {
            return hours == 1 ? "1 H AGO" : "\(hours) H AGO"
        }

        return DateFormatters.shortDateTime(date)
    }
}

#Preview {
    ContentView()
}
