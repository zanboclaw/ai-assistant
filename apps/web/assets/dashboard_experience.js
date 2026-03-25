(function registerDashboardExperience(globalScope) {
  function safeArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function buildRuntimeVersionSummary(runtimeMetadata = {}) {
    const versionMetadata = runtimeMetadata.version || {};
    const lines = [];
    if (versionMetadata.current_version) {
      lines.push(`版本：${versionMetadata.current_version}`);
    }
    if (versionMetadata.git_short_commit || versionMetadata.git_branch) {
      lines.push(
        `提交：${versionMetadata.git_short_commit || "-"}${versionMetadata.git_branch ? ` @ ${versionMetadata.git_branch}` : ""}${versionMetadata.git_dirty ? " (dirty)" : ""}`
      );
    }
    if (versionMetadata.build_timestamp) {
      lines.push(`构建时间：${versionMetadata.build_timestamp}`);
    }
    return lines.join("\n");
  }

  function formatRetrievedMemoriesForDisplay(retrievedMemories = [], options = {}) {
    const includeContent = options.includeContent !== false;
    const includeCitationHint = Boolean(options.includeCitationHint);
    const rows = safeArray(retrievedMemories)
      .slice(0, options.limit || 4)
      .map((item, index) => {
        const metadata = item.metadata || {};
        const lines = [`${index + 1}. [${item.memory_kind || "memory"}] ${item.title || ""}`.trim()];
        if (includeContent && item.content) {
          lines.push(String(item.content || "").trim());
        }
        if (metadata.match_explanation) {
          lines.push(`命中原因：${metadata.match_explanation}`);
        }
        if (includeCitationHint && metadata.citation_hint) {
          lines.push(`引用建议：${metadata.citation_hint}`);
        }
        return lines.filter(Boolean).join("\n");
      })
      .filter(Boolean);
    return rows.length ? rows.join("\n\n") : "暂无可复用长期记忆";
  }

  globalScope.DashboardExperience = {
    buildRuntimeVersionSummary,
    formatRetrievedMemoriesForDisplay,
  };
})(window);
