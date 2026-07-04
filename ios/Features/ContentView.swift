import SwiftUI

struct ContentView: View {
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
                        mainStatusCard
                        metricsRow
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
                viewModel.reloadSyncState()
                viewModel.refreshStatuses()
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

    private var mainStatusCard: some View {
        DashboardCard(title: "SYNC STATUS", accent: HEColor.accentGreen) {
            ViewThatFits {
                HStack(alignment: .center, spacing: 20) {
                    mainStatusLeftColumn
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .layoutPriority(1)

                    syncRing
                        .frame(maxWidth: .infinity)
                        .layoutPriority(2)

                    mainStatusRightColumn
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                VStack(alignment: .leading, spacing: 18) {
                    HStack(alignment: .center, spacing: 20) {
                        mainStatusLeftColumn
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .layoutPriority(1)

                        syncRing
                            .frame(maxWidth: .infinity)
                    }

                    mainStatusRightColumn
                }
            }
        }
    }

    private var mainStatusLeftColumn: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("HEALTHKIT INGESTION")
                .font(HETypography.overline)
                .foregroundStyle(HEColor.secondaryText)
                .tracking(1.2)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            Text(mainStatusText)
                .font(HETypography.status)
                .foregroundStyle(HEColor.primaryText)
                .lineLimit(1)
                .minimumScaleFactor(0.85)

            Text(mainStatusSubtitle)
                .font(HETypography.body)
                .foregroundStyle(HEColor.secondaryText)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var mainStatusRightColumn: some View {
        VStack(alignment: .leading, spacing: 12) {
            MetricRow(title: "LAST SYNC", value: viewModel.lastSyncDisplayText)
            MetricRow(title: "ITEMS SENT", value: "\(viewModel.syncState.lastSentItemCount)")
            MetricRow(title: "SYNC MODE", value: viewModel.lastSyncModeDisplayText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var syncRing: some View {
        ZStack {
            Circle()
                .stroke(HEColor.border, lineWidth: 10)
                .frame(width: 124, height: 124)

            Circle()
                .trim(from: 0, to: ringTrim)
                .stroke(
                    AngularGradient(
                        colors: [HEColor.accentGreen, HEColor.accentCyan],
                        center: .center
                    ),
                    style: StrokeStyle(lineWidth: 10, lineCap: .round)
                )
                .frame(width: 124, height: 124)
                .rotationEffect(.degrees(-90))

            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(HEColor.accentCyan)
        }
        .frame(minWidth: 124, minHeight: 124)
    }

    private var metricsRow: some View {
        ViewThatFits {
            HStack(alignment: .top, spacing: 16) {
                loadStateCard
                recoveryDataCard
            }

            VStack(alignment: .leading, spacing: 16) {
                loadStateCard
                recoveryDataCard
            }
        }
    }

    private var loadStateCard: some View {
        DashboardCard(title: "LOAD STATE", accent: HEColor.accentYellow, secondaryBackground: true) {
            VStack(alignment: .leading, spacing: 12) {
                Text("BACKEND OWNED")
                    .font(HETypography.title)
                    .foregroundStyle(HEColor.primaryText)
                    .lineLimit(1)
                    .minimumScaleFactor(0.9)

                Text("Strava data synced separately. Load, readiness, and recommendation logic stay on the backend.")
                    .font(HETypography.body)
                    .foregroundStyle(HEColor.secondaryText)
                    .lineLimit(3)

                placeholderBars(color: HEColor.accentYellow)
            }
        }
    }

    private var recoveryDataCard: some View {
        DashboardCard(title: "RECOVERY DATA", accent: HEColor.accentCyan, secondaryBackground: true) {
            VStack(alignment: .leading, spacing: 12) {
                MetricRow(title: "SLEEP NIGHTS", value: "\(viewModel.sleepNightAggregates.count)", valueColor: HEColor.accentGreen)
                MetricRow(title: "HRV SAMPLES", value: "\(viewModel.hrvSamples.count)", valueColor: HEColor.accentCyan)
                MetricRow(title: "REST HR DAYS", value: "\(viewModel.restingHRSamples.count)", valueColor: HEColor.accentYellow)
                MetricRow(title: "LATEST WEIGHT", value: viewModel.latestWeightValue)
                MetricRow(title: "SYNC MODE", value: viewModel.lastSyncModeDisplayText)
            }
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
                        title: "BACKFILL",
                        subtitle: "Since May 23",
                        icon: "calendar",
                        accent: HEColor.accentPurple
                    ) {
                        viewModel.runBackfillSinceMay23FromMainScreen()
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

    private func placeholderBars(color: Color) -> some View {
        HStack(alignment: .bottom, spacing: 8) {
            ForEach([18.0, 34.0, 22.0, 40.0, 28.0], id: \.self) { height in
                RoundedRectangle(cornerRadius: 4)
                    .fill(color.opacity(0.3))
                    .frame(height: height)
            }
        }
        .frame(height: 46, alignment: .bottom)
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

    private var mainStatusText: String {
        if viewModel.syncState.lastErrorMessage != nil {
            return "CHECK"
        }

        if viewModel.syncState.lastSuccessfulSyncAt != nil {
            return "SYNC OK"
        }

        return "READY"
    }

    private var mainStatusSubtitle: String {
        if let error = viewModel.syncState.lastErrorMessage, !error.isEmpty {
            return error
        }

        return "READY TO SYNC"
    }

    private var ringTrim: CGFloat {
        let value = min(max(CGFloat(viewModel.syncState.lastSentItemCount) / 100.0, 0.18), 0.92)
        return value
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
