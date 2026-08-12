import { useEffect, useState } from 'react'
import { Wrench, CheckCircle2, XCircle, RefreshCw, ExternalLink } from 'lucide-react'
import { api, type CLITool } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'


interface CLIToolsProps {
  embedded?: boolean
}

export default function CLITools({ embedded = false }: CLIToolsProps) {
  const [tools, setTools] = useState<CLITool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detecting, setDetecting] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api.listCliTools()
      .then(setTools)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const detect = async (name: string) => {
    setDetecting(name)
    try {
      const result = await api.detectCliTool(name)
      setTools((prev) =>
        prev.map((t) => (t.name === name ? result : t)),
      )
    } catch (e) {
      console.error(`Detect failed for ${name}:`, e)
    } finally {
      setDetecting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
        Loading CLI tools...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-20 text-destructive">
        <XCircle className="mr-2 h-5 w-5" />
        {error}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {!embedded && (
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">CLI Tools</h1>
            <p className="text-sm text-muted-foreground">
              Manage external CLI tools used by StreamDoc for integration backends
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {tools.map((tool) => (
          <Card key={tool.name} className={tool.installed ? 'border-green-500/30' : 'border-amber-500/30'}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Wrench className="h-4 w-4 text-muted-foreground" />
                  <CardTitle className="text-base">{tool.name}</CardTitle>
                  <Badge variant={tool.installed ? 'default' : 'secondary'} className="text-[10px]">
                    {tool.installed ? (
                      <><CheckCircle2 className="mr-1 h-3 w-3" /> Installed</>
                    ) : (
                      <><XCircle className="mr-1 h-3 w-3" /> Not Found</>
                    )}
                  </Badge>
                </div>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => detect(tool.name)}
                    disabled={detecting === tool.name}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${detecting === tool.name ? 'animate-spin' : ''}`} />
                  </Button>
                  {!tool.installed && tool.install_url && (
                    <a
                      href={tool.install_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Button variant="outline" size="sm">
                        <ExternalLink className="mr-1 h-3.5 w-3.5" />
                        Install Docs
                      </Button>
                    </a>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {tool.installed && tool.version && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span className="font-medium">Version:</span>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{tool.version}</code>
                </div>
              )}
              {tool.installed && tool.binary_path && (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span className="font-medium">Path:</span>
                  <code className="truncate rounded bg-muted px-1.5 py-0.5 text-xs">{tool.binary_path}</code>
                </div>
              )}
              {tool.install_instructions && (
                <div className="mt-2 rounded border bg-muted/50 p-3">
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <ExternalLink className="h-3 w-3" />
                    Install Instructions
                  </div>
                  <pre className="whitespace-pre-wrap text-xs text-muted-foreground">
                    {tool.install_instructions}
                  </pre>
                </div>
              )}
              {!tool.installed && !tool.install_instructions && (
                <p className="text-xs text-muted-foreground">
                  Use the Install button above to attempt auto-detection and setup.
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {tools.length === 0 && (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <p>No CLI tools registered.</p>
        </div>
      )}
    </div>
  )
}
