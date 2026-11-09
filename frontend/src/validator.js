// Data-quality rules for a place of worship, as pure functions of its
// properties. Each rule has a stable id: the id is used by the improve-mode
// filter buttons (data-improve), permalinks, exports and quick fixes, so
// never rename one.
//
// check(props, ctx) returns null when the place passes, or an issue
// { title_ar, title_en }. ctx holds the user-adjustable thresholds and the
// current time, so the rules stay testable.
import { ArabicText } from './arabic.js';
import { outdatedRules, describeUpgrade } from './presets.js';

const FIVE_YEARS_MS = 5 * 365 * 24 * 60 * 60 * 1000;

function arabicName(props) {
  return (props.name_original || props['name:ar'] || props.name_ar || props.name_ar_original || '').trim();
}

// Rules run in this order, which is also the order issues are listed in.
export const RULES = [
  {
    // building=mosque without amenity=place_of_worship
    id: 'missing_amenity',
    check: props => (props.building === 'mosque' && props.amenity !== 'place_of_worship' ? {
      title_ar: 'مبنى مسجد بدون تصنيف (amenity=place_of_worship)',
      title_en: 'Building marked as mosque but missing amenity=place_of_worship',
    } : null),
  },
  {
    // Empty, only generic words like "مسجد", or default name in Latin without Arabic
    id: 'missing_name',
    check: props => {
      const name = arabicName(props);
      if (!name || ArabicText.isGenericMosqueName(name)) {
        return {
          title_ar: 'اسم المسجد مفقود أو افتراضي (مثال: "مسجد")',
          title_en: 'Mosque name is missing or set to a generic default',
        };
      }
      if (!/[\u0600-\u06FF]/.test(name) && /[a-zA-Z]/.test(name)) {
        return {
          title_ar: 'الاسم الافتراضي (name) مكتوب باللاتينية بدلاً من العربية',
          title_en: 'Default name (name) is in Latin script instead of Arabic',
        };
      }
      return null;
    },
  },
  {
    // name:en missing, identical to Arabic name, or containing Arabic characters.
    // Places without a real Arabic name are left out (missing_name covers them).
    id: 'missing_name_en',
    check: props => {
      const nameAr = arabicName(props);
      if (!nameAr || ArabicText.isGenericMosqueName(nameAr)) return null;
      const nameEn = (props.name_en_original || props['name:en'] || '').trim();
      const hasArabicInEn = /[\u0600-\u06FF]/.test(nameEn);
      return !nameEn || nameAr === nameEn || hasArabicInEn ? {
        title_ar: 'الاسم بالإنجليزية مفقود أو مطابق للاسم العربي أو يحوي حروفاً عربية',
        title_en: 'English name translation (name:en) is missing, untranslated, or contains Arabic script',
      } : null;
    },
  },
  {
    id: 'missing_denom',
    check: props => (props.religion === 'muslim' && (!props.denomination || props.denomination === 'unknown') ? {
      title_ar: 'المذهب غير محدد (سني/شيعي)',
      title_en: 'Denomination is unknown or unspecified',
    } : null),
  },
  {
    id: 'size_too_small',
    check: (props, ctx) => (typeof props.size_area_m2 === 'number' && props.size_area_m2 < ctx.sizeMinM2 ? {
      title_ar: 'مبنى المسجد أصغر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى',
      title_en: 'Mosque building footprint looks too small — verify the building outline',
    } : null),
  },
  {
    // Never both: a place below the minimum is only reported as too small.
    id: 'size_too_large',
    check: (props, ctx) => (typeof props.size_area_m2 === 'number'
      && props.size_area_m2 >= ctx.sizeMinM2 && props.size_area_m2 > ctx.sizeMaxM2 ? {
        title_ar: 'مبنى المسجد أكبر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى',
        title_en: 'Mosque building footprint looks too large — verify the building outline',
      } : null),
  },
  {
    // Still version 1, and first mapped more than five years ago
    id: 'stale_data',
    check: (props, ctx) => (props.version === 1 && props.edited_at
      && (ctx.now - new Date(props.edited_at).getTime()) > FIVE_YEARS_MS ? {
        title_ar: 'لم يتم تعديل هذا العنصر منذ إضافته لأول مرة (بيانات قديمة)',
        title_en: 'This entry has never been revisited since it was first mapped',
      } : null),
  },
  {
    id: 'building_yes',
    check: props => (props.religion === 'muslim' && props.building === 'yes' ? {
      title_ar: 'مبنى مسجد مصنف كـ building=yes بدلاً من building=mosque',
      title_en: 'Mosque building tagged as building=yes instead of building=mosque',
    } : null),
  },
  {
    // A single point instead of a traced building outline, so the true size
    // and shape don't show on the map
    id: 'mapped_as_node',
    check: props => (props.geom_type === 'Point' ? {
      title_ar: 'مرسوم كنقطة وليس كمساحة (مبنى) — يفضّل رسم حدود المبنى',
      title_en: 'Mapped as a single node instead of an area — ideally traced as a building outline',
    } : null),
  },
  {
    // Isolation Forest verdict from detect_geometry_anomalies.py
    id: 'ml_geometry_anomaly',
    check: props => (props.ml_anomaly && props.ml_anomaly.is_anomaly ? {
      title_ar: `🤖 شذوذ هندسي (ذكاء اصطناعي): ${props.ml_anomaly.diagnosis}`,
      title_en: `🤖 ML Geometry Anomaly: ${props.ml_anomaly.diagnosis_en || props.ml_anomaly.diagnosis}`,
    } : null),
  },
  {
    // The building outline and a point inside it both carry
    // amenity=place_of_worship (merged into one place by extract_places.py)
    id: 'duplicate_poi',
    check: props => (props.duplicate_poi ? {
      title_ar: 'مكرر: المبنى ونقطة داخله كلاهما موسوم كدار عبادة — يُفضّل نقل الوسوم إلى المبنى وحذف النقطة',
      title_en: 'Mapped twice: both the building and a point inside it are tagged as the place of worship',
    } : null),
  },
  {
    // Values the preset's upgrade rules fix (iD's deprecated.json plus
    // Manara's, e.g. denomination=سني -> sunni), plus pious eulogies inside name
    id: 'outdated_tags',
    check: props => {
      const outdated = outdatedRules(props);
      const changes = describeUpgrade(props, outdated);
      const name = arabicName(props);
      if (name && ArabicText.hasEulogy(name)) {
        changes.push('عبارة تبجيل في الاسم (eulogy in name)');
      }
      if (!changes.length) return null;
      return {
        title_ar: `وسوم قديمة أو بصيغة غير معتمدة (${changes.join('، ')})`,
        title_en: `Outdated or non-standard tags (${changes.join(', ')})`,
      };
    },
  },
  {
    id: 'qibla_deviation',
    check: (props, ctx) => {
      const a = props.ml_anomaly;
      if (!a || typeof a.qibla_dev !== 'number' || a.qibla_dev < ctx.qiblaDevThreshold) return null;
      return {
        title_ar: `🕋 انحراف حاد عن القبلة (${a.qibla_dev}° — سمت القبلة ${a.qibla_az}° مقابل ${a.bldg_az}° لمحور المبنى)`,
        title_en: `🕋 Severe Qibla deviation (${a.qibla_dev}°: Qibla bearing ${a.qibla_az}° vs building axis ${a.bldg_az}°)`,
      };
    },
  },
];

export const RULE_IDS = RULES.map(r => r.id);

// All issues for a place: [{ id, title_ar, title_en }, ...] in rule order.
export function evaluateRules(props, ctx = {}) {
  const safeCtx = {
    now: Date.now(),
    sizeMinM2: 50,
    sizeMaxM2: 10000,
    qiblaDevThreshold: 20.0,
    ...(ctx || {}),
  };
  const issues = [];
  for (const rule of RULES) {
    try {
      const issue = rule.check(props, safeCtx);
      if (issue) issues.push({ id: rule.id, ...issue });
    } catch (_) {}
  }
  return issues;
}
