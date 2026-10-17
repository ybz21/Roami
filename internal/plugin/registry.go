package plugin

// builtinManifests is populated by the builtin package's init (builtin 依赖
// plugin,反向用注册钩子解耦,避免 import 环)。
var builtinManifests []Manifest

// RegisterBuiltinManifest is called from builtin package init.
func RegisterBuiltinManifest(m Manifest) {
	builtinManifests = append(builtinManifests, m)
}

// SyncBuiltins upserts all registered builtin manifests into the registry.
func SyncBuiltins(s *Store) error {
	s.migrateRenamedBuiltins()
	for _, m := range builtinManifests {
		if err := m.Validate(); err != nil {
			return err
		}
		if err := s.SyncBuiltin(m); err != nil {
			return err
		}
	}
	return nil
}
