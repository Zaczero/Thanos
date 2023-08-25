import { renderChangesets } from './render.js'

for (const e of document.querySelectorAll('.tagify')) {
    new Tagify(e)
}

if (window.changesets) {
    for (const cs of Object.values(window.changesets)) {
        if (cs.user)
            cs['@user'] = cs.user.display_name
        else
            cs['@user'] = `user_${cs['@uid']}`

        if (!cs.tags)
            cs.tags = { 'comment': '(no comment)' }
        else if (!cs.tags.comment)
            cs.tags.comment = '(no comment)'

        cs['_deleted'] = !cs.user
        cs['_blocked'] = cs.user && cs['user']['blocks']['received']['active']
    }

    renderChangesets(window.changesets)
}
