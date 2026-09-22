/** DOM ids shared by a tab and its panel so `aria-controls` / `aria-labelledby` line up. */
export function tabDomIds(id) {
  return { tab: `tab-${id}`, panel: `tabpanel-${id}` };
}
