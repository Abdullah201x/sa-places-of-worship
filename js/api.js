/**
 * Backend API Client for Saudi Places of Worship Map.
 * Provides seamless communication with the Flask REST backend,
 * automatic review mark syncing, community notes, and system health status.
 */

const BackendApi = {
  isOnline: false,
  communityStats: null,

  async checkHealth() {
    try {
      const res = await fetch('/api/health', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        this.isOnline = (data.status === 'healthy' || data.status === 'degraded');
        this.updateStatusBadge(true);
        return data;
      }
    } catch (e) {
      this.isOnline = false;
      this.updateStatusBadge(false);
    }
    return null;
  },

  updateStatusBadge(online) {
    const pill = document.getElementById('backend-status-pill');
    if (!pill) return;
    if (online) {
      pill.classList.remove('offline');
      pill.classList.add('online');
      pill.innerHTML = '<span class="status-dot"></span> <span class="status-text">' + t('backendOnline') + '</span>';
      pill.title = t('backendOnlineTitle');
    } else {
      pill.classList.remove('online');
      pill.classList.add('offline');
      pill.innerHTML = '<span class="status-dot"></span> <span class="status-text">' + t('backendOffline') + '</span>';
      pill.title = t('backendOfflineTitle');
    }
  },

  async syncReviews(localMarks, userName) {
    if (!this.isOnline) return null;
    try {
      const res = await fetch('/api/reviews/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ marks: localMarks, user_name: userName || null })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.stats) {
          this.communityStats = data.stats;
          this.renderCommunityStats(data.stats);
        }
        return data.marks;
      }
    } catch (e) {
      console.warn('BackendApi: Failed to sync reviews:', e);
    }
    return null;
  },

  async setReview(osmType, osmId, status, version, userName) {
    if (!this.isOnline) return;
    try {
      const res = await fetch('/api/reviews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          osm_type: osmType,
          osm_id: osmId,
          status: status,
          version: version,
          user_name: userName || null
        })
      });
      if (res.ok) {
        this.fetchReviewStats();
      }
    } catch (e) {
      console.warn('BackendApi: setReview failed:', e);
    }
  },

  async clearReview(osmType, osmId, userName) {
    if (!this.isOnline) return;
    try {
      const url = `/api/reviews/${encodeURIComponent(osmType)}/${encodeURIComponent(osmId)}` +
                  (userName ? `?user_name=${encodeURIComponent(userName)}` : '');
      const res = await fetch(url, { method: 'DELETE' });
      if (res.ok) {
        this.fetchReviewStats();
      }
    } catch (e) {
      console.warn('BackendApi: clearReview failed:', e);
    }
  },

  async fetchReviewStats() {
    if (!this.isOnline) return;
    try {
      const res = await fetch('/api/reviews/stats');
      if (res.ok) {
        const stats = await res.json();
        this.communityStats = stats;
        this.renderCommunityStats(stats);
      }
    } catch (e) {}
  },

  renderCommunityStats(stats) {
    const el = document.getElementById('review-community-count');
    if (!el || !stats) return;
    el.textContent = t('reviewedCommunityToday', { n: stats.reviewed_today, total: stats.fixed_count });
    el.style.display = 'inline-block';
  },

  async getNotes(osmType, osmId) {
    if (!this.isOnline) return [];
    try {
      const res = await fetch(`/api/notes/${encodeURIComponent(osmType)}/${encodeURIComponent(osmId)}`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn('BackendApi: getNotes failed:', e);
    }
    return [];
  },

  async addNote(osmType, osmId, content, userName) {
    if (!this.isOnline) return null;
    try {
      const res = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          osm_type: osmType,
          osm_id: osmId,
          content: content,
          user_name: userName || null
        })
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn('BackendApi: addNote failed:', e);
    }
    return null;
  },

  async getPipelineStatus() {
    try {
      const res = await fetch('/api/pipeline/status');
      if (res.ok) return await res.json();
    } catch (e) {}
    return null;
  },

  async validatePipeline() {
    try {
      const res = await fetch('/api/pipeline/validate', { method: 'POST' });
      return await res.json();
    } catch (e) {
      return { is_valid: false, errors: [e.message] };
    }
  }
};
