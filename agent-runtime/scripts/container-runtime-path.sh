# Login shells must retain the tools installed in the offline agent environment.
if [ -x /opt/roami-agent/.venv/bin/python ]; then
    export VIRTUAL_ENV=/opt/roami-agent/.venv
    case ":${PATH}:" in
        *":${VIRTUAL_ENV}/bin:"*) ;;
        *) export PATH="${VIRTUAL_ENV}/bin:${PATH}" ;;
    esac
fi
