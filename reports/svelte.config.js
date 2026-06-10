// Evidence deep-merges this into its generated SvelteKit config. We downgrade
// prerender link/id errors to warnings so a single broken data-driven link
// cannot fail the scheduled production build of the dashboard. Real link
// correctness is still handled in the page SQL (base-path-aware hrefs).
export default {
  kit: {
    prerender: {
      handleHttpError: 'warn',
      handleMissingId: 'warn'
    }
  }
};
