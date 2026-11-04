import { useCallback, useEffect, useState } from 'react'
import { getApiErrorMessage } from '../services/http'
import { projectApi, type ProjectListQuery } from '../services/projects'
import type { Project, ProjectInput } from '../types'

export function useProjects(query: ProjectListQuery = {}) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { status, includeArchived, search } = query

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await projectApi.list({ status, includeArchived, search })
      setProjects(data)
      return true
    } catch (loadError) {
      setError(getApiErrorMessage(loadError))
      return false
    } finally {
      setLoading(false)
    }
  }, [status, includeArchived, search])

  useEffect(() => {
    let active = true
    projectApi
      .list({ status, includeArchived, search })
      .then((data) => {
        if (active) {
          setProjects(data)
          setError(null)
        }
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(getApiErrorMessage(loadError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [status, includeArchived, search])

  const createProject = useCallback(async (input: ProjectInput) => {
    const created = await projectApi.create(input)
    setProjects((current) => [created, ...current])
    return created
  }, [])

  const editProject = useCallback(
    async (projectId: string, input: Partial<ProjectInput>) => {
      const updated = await projectApi.update(projectId, input)
      setProjects((current) =>
        current.map((project) => (project.id === projectId ? updated : project)),
      )
      return updated
    },
    [],
  )

  const archiveProject = useCallback(async (projectId: string) => {
    const updated = await projectApi.archive(projectId)
    setProjects((current) =>
      current.map((project) => (project.id === projectId ? updated : project)),
    )
    return updated
  }, [])

  const restoreProject = useCallback(async (projectId: string) => {
    const updated = await projectApi.restore(projectId)
    setProjects((current) =>
      current.map((project) => (project.id === projectId ? updated : project)),
    )
    return updated
  }, [])

  return {
    projects,
    loading,
    error,
    reload: load,
    createProject,
    editProject,
    archiveProject,
    restoreProject,
  }
}
