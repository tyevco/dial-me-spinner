import { posix } from 'node:path'
import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

const REPO = 'https://github.com/tyevco/dial-me-spinner'

// The site is built from the repository root, so the relative links that work on GitHub work here too.
// Links to anything that is not a page (Python, KiCad, OpenSCAD, folders...) go to the file on GitHub.
function repoLinks(md: any) {
  const next = md.renderer.rules.link_open ??
    ((tokens: any, idx: number, options: any, _env: any, self: any) => self.renderToken(tokens, idx, options))
  md.renderer.rules.link_open = (tokens: any, idx: number, options: any, env: any, self: any) => {
    const token = tokens[idx]
    const href: string | null = token.attrGet('href')
    if (href && !/^([a-z][a-z0-9+.-]*:|#|\/)/i.test(href)) {
      const [path, hash] = href.split('#')
      const isPage = path === '' || /\.(md|html)$/i.test(path)
      if (!isPage) {
        const target = posix.normalize(posix.join(posix.dirname(env.relativePath ?? ''), path))
        const kind = path.endsWith('/') ? 'tree' : 'blob'
        token.attrSet('href', `${REPO}/${kind}/main/${target.replace(/\/$/, '')}${hash ? '#' + hash : ''}`)
      }
    }
    return next(tokens, idx, options, env, self)
  }
}

export default withMermaid(defineConfig({
  title: 'dial-me-spinner',
  description: 'A Ø70 mm Bluetooth dial spinner: nRF52840, OLED, 48-LED ring, switchable magnetic detents, press click.',
  base: '/dial-me-spinner/',
  lang: 'en-US',
  cleanUrls: true,
  lastUpdated: true,
  // README.md is the home page; everything else keeps its repository path as its URL
  rewrites: { 'README.md': 'index.md' },
  srcExclude: ['hardware/kicad/**', 'hardware/fab/**', '**/node_modules/**', '.github/**'],
  markdown: {
    config: (md) => { md.use(repoLinks) },
    languageAlias: { dts: 'c', conf: 'ini' },   // devicetree and Kconfig snippets in the firmware doc
  },
  vite: { build: { chunkSizeWarningLimit: 3000 } },   // mermaid is one large chunk
  themeConfig: {
    nav: [
      { text: 'Architecture', link: '/docs/architecture' },
      { text: 'SPEC', link: '/hardware/design/SPEC' },
      { text: 'Simulation', link: '/docs/simulation' },
      { text: 'GitHub', link: REPO },
    ],
    sidebar: [
      {
        text: 'Overview',
        items: [
          { text: 'Introduction', link: '/' },
          { text: 'Architecture', link: '/docs/architecture' },
          { text: 'SPEC (architecture of record)', link: '/hardware/design/SPEC' },
          { text: 'Display study (rev B)', link: '/docs/display-study' },
        ],
      },
      {
        text: 'Hardware',
        items: [
          { text: 'Mechanical design', link: '/docs/mechanical' },
          { text: 'Enclosure model', link: '/hardware/mechanical/README' },
          { text: 'Assembly and ordering', link: '/docs/assembly' },
          { text: 'Bring-up', link: '/docs/bringup' },
          { text: 'Design toolchain', link: '/hardware/tools/README' },
        ],
      },
      {
        text: 'Firmware',
        items: [{ text: 'Firmware design', link: '/docs/firmware' }],
      },
      {
        text: 'Verification',
        items: [
          { text: 'SPICE simulation', link: '/docs/simulation' },
          { text: 'Latest simulation results', link: '/hardware/sim/results/report' },
        ],
      },
    ],
    outline: { level: [2, 3] },
    search: { provider: 'local' },
    socialLinks: [{ icon: 'github', link: REPO }],
    editLink: { pattern: `${REPO}/edit/main/:path`, text: 'Edit this page on GitHub' },
    footer: { message: 'Hardware design files, docs and generators for dial-me-spinner.' },
  },
  mermaid: {},
}))
