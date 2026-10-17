package app

import "github.com/ybz21/Roami/internal/application"

func (a App) Sessions() application.SessionService {
	a.migrateSessionsToID()
	return application.NewSessions(a.rt, a.meta(), a.swarmSessions())
}
