import { useRef } from 'react'
import { api } from '../../api'
import type { useI18n } from '../../i18n'
import type { ModelChoice } from '../capabilities/ModelSelectionFields'
import { nodeApi } from '../cluster/node-url'
import { refreshSessionLists } from './native-session-list'
import { lifecycleRequestError } from './session-lifecycle'

export function useNativeSessionCreate() {
  const request = useRef<{ signature: string; key: string } | null>(null)
  return {
    reset: () => { request.current = null },
    create: async (title: string, task: string, directory: string, choice: ModelChoice) => {
      const route = '/agent/native-sessions'
      const destination = nodeApi(route)
      const body = {
        title: title.slice(0, 80), task, directory: directory || undefined,
        model: choice.model !== 'auto' || choice.freeOnly ? choice.model : undefined, freeOnly: choice.freeOnly,
      }
      const signature = JSON.stringify([destination, body])
      if (request.current?.signature !== signature) request.current = { signature, key: crypto.randomUUID() }
      const requestKey = request.current.key
      const { data } = await api('POST', route, { ...body, requestKey })
      if (request.current?.key === requestKey) request.current = null
      const onCurrentNode = nodeApi(route) === destination
      if (onCurrentNode) refreshSessionLists()
      return { session: data.session as string, onCurrentNode }
    },
  }
}

export function sessionCreateError(error: unknown, t: ReturnType<typeof useI18n>['t']) {
  const failure = error as { apiError?: { code?: string }; message?: string } | null
  switch (failure?.apiError?.code || failure?.message) {
    case 'MODEL_NOT_CONFIGURED': return t('modelSelection.notConfigured')
    case 'MODEL_ROUTE_DISABLED': return t('modelSelection.disabled')
    case 'MODEL_ROLE_REQUIRES_BINDING': return t('agent.models.bindRoles')
    default: return lifecycleRequestError(error, t)
  }
}
