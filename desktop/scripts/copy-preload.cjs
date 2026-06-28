const { copyFileSync, mkdirSync } = require('node:fs')
const { join } = require('node:path')

const root = join(__dirname, '..')
const outputDir = join(root, 'dist', 'preload')

mkdirSync(outputDir, { recursive: true })
copyFileSync(join(root, 'src', 'preload', 'preload.cjs'), join(outputDir, 'preload.cjs'))
