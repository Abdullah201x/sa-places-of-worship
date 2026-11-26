import { describe, it, expect } from 'vitest';
import {
  formatBytes,
  buildOverpassTurboUrl,
  formatShaBadge,
  filterManifestFiles,
} from '../src/data_view.js';

describe('Data Hub View Helpers', () => {
  describe('formatBytes', () => {
    it('formats bytes into B, KB, and MB', () => {
      expect(formatBytes(0)).toBe('0 B');
      expect(formatBytes(512)).toBe('512 B');
      expect(formatBytes(1024)).toBe('1.0 KB');
      expect(formatBytes(2048)).toBe('2.0 KB');
      expect(formatBytes(1572864)).toBe('1.5 MB');
      expect(formatBytes(6412875)).toBe('6.1 MB');
    });

    it('handles negative or invalid values gracefully', () => {
      expect(formatBytes(-100)).toBe('0 B');
      expect(formatBytes(null)).toBe('0 B');
      expect(formatBytes(undefined)).toBe('0 B');
      expect(formatBytes('abc')).toBe('0 B');
    });
  });

  describe('buildOverpassTurboUrl', () => {
    it('constructs an overpass-turbo URL with encoded query', () => {
      const q = 'nwr["amenity"="place_of_worship"]; out;';
      const url = buildOverpassTurboUrl(q);
      expect(url).toContain('https://overpass-turbo.eu/?Q=');
      expect(url).toContain(encodeURIComponent(q));
    });

    it('injects dynamic bbox when provided', () => {
      const q = 'nwr["amenity"="place_of_worship"]({{bbox}}); out;';
      const bbox = '24.1,46.5,24.9,47.2';
      const url = buildOverpassTurboUrl(q, bbox);
      expect(url).toContain(encodeURIComponent('nwr["amenity"="place_of_worship"](24.1,46.5,24.9,47.2); out;'));
    });

    it('prepends bbox clause if query lacks {{bbox}} template', () => {
      const q = 'nwr["amenity"="place_of_worship"]; out;';
      const bbox = '24.1,46.5,24.9,47.2';
      const url = buildOverpassTurboUrl(q, bbox);
      expect(decodeURIComponent(url)).toContain('[bbox:24.1,46.5,24.9,47.2];');
    });

    it('handles empty query', () => {
      expect(buildOverpassTurboUrl('')).toBe('https://overpass-turbo.eu/');
      expect(buildOverpassTurboUrl(null)).toBe('https://overpass-turbo.eu/');
    });
  });

  describe('formatShaBadge', () => {
    it('abbreviates sha256 hashes cleanly', () => {
      const sha = '2a96bb29d746aef07b475138d7f4a58a18bf6639dc385a17da2366d11a341983';
      const badge = formatShaBadge(sha);
      expect(badge).toBe('2a96bb29…341983');
    });

    it('returns empty string on empty input', () => {
      expect(formatShaBadge('')).toBe('');
      expect(formatShaBadge(null)).toBe('');
    });
  });

  describe('filterManifestFiles', () => {
    const files = [
      { id: 'places-sa-geojson', scope: 'SA', layer: 'places', format: 'geojson', path: 'places_of_worship_sa.geojson' },
      { id: 'places-sa-csv', scope: 'SA', layer: 'places', format: 'csv', path: 'places_of_worship_sa.csv' },
      { id: 'places-SA-01-geojson', scope: 'SA-01', layer: 'places', format: 'geojson', path: 'by-region/places_SA-01.geojson' },
      { id: 'places-SA-01-csv', scope: 'SA-01', layer: 'places', format: 'csv', path: 'by-region/places_SA-01.csv' },
      { id: 'gaps-sa-json', scope: 'SA', layer: 'gaps', format: 'geojson', path: 'worship_gaps_sa.json' },
      { id: 'suggestions-sa-csv', scope: 'SA', layer: 'suggestions', format: 'csv', path: 'suggested_mosques_sa.csv' },
      { id: 'boundary-sa-geojson', scope: 'SA', layer: 'boundary', format: 'geojson', path: 'sa_boundary.geojson' },
    ];

    it('filters by layer', () => {
      const filtered = filterManifestFiles(files, { layer: 'places' });
      expect(filtered.length).toBe(4);
      expect(filtered.every(f => f.layer === 'places')).toBe(true);
    });

    it('filters by format', () => {
      const filtered = filterManifestFiles(files, { format: 'csv' });
      expect(filtered.length).toBe(3);
      expect(filtered.every(f => f.format === 'csv')).toBe(true);
    });

    it('filters by scope', () => {
      const filtered = filterManifestFiles(files, { scope: 'SA-01' });
      expect(filtered.length).toBe(2);
      expect(filtered.every(f => f.scope === 'SA-01')).toBe(true);
    });

    it('filters by search query matching scope', () => {
      const filtered = filterManifestFiles(files, { query: 'SA-01' });
      expect(filtered.length).toBe(2);
      expect(filtered[0].id).toBe('places-SA-01-geojson');
    });

    it('combines multiple filter criteria with scope', () => {
      const filtered = filterManifestFiles(files, { scope: 'SA-01', format: 'csv' });
      expect(filtered.length).toBe(1);
      expect(filtered[0].id).toBe('places-SA-01-csv');
    });
  });
});
