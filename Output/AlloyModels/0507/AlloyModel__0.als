// Alloy 6 Model: RBAC Emergency Module (Abstract, Requirements-driven)

// --------- MODULES AND ENUMS ----------
open util/ordering[State] as Time

// Clearance and Classification levels
abstract sig ClearanceLevel {}
one sig High, Medium, Low extends ClearanceLevel {}

abstract sig ClassificationLevel {}
one sig C_High, C_Medium, C_Low extends ClassificationLevel {}

// System modes
abstract sig SystemMode {}
one sig Normal, Emergency extends SystemMode {}

// --------- CORE ENTITIES -------------

sig User {
    clearance: one ClearanceLevel,
    isAdmin: one Bool // For abstract admin marking
}

sig Administrator in User {} // Admins are Users with High clearance

sig Role {
    mutuallyExclusiveWith: set Role // mutual exclusion
}

sig Object {
    classification: one ClassificationLevel
}

// Each Request is classified by the highest classification of affected objects
sig Request {
    requestedBy: one User,
    affects: some Object, // Never empty
    classification: one ClassificationLevel
}

// Delegations: who, what, and when
sig Delegation {
    delegatee: one User,
    role: one Role,
    delegatedAt: one State,
    expiresAt: lone State // None means not yet expired
    // Not modeling revocation as a field; will abstract via predicates
}

// Emergency privilege assignment
sig EmergencyPrivilege {
    admin: one Administrator,
    grantedAt: one State,
    revokedAt: lone State // None if active
}

// --------- SYSTEM STATE --------------
sig State {
    // System mode at this state
    mode: one SystemMode,
    // Which two admins (if any) triggered Emergency (fixed per Emergency episode)
    emAdmins: set Administrator, // Only non-empty in Emergency mode
    // Requests in system at this state
    requests: set Request,
    // Delegations active at this state
    delegations: set Delegation,
    // Emergency privileges active at this state
    emPrivs: set EmergencyPrivilege,
    // Credentials needing update at this state (post-Emergency)
    needsCredentialUpdate: set Administrator
}

// Time ordering
fact StateOrdering {
    // All states are totally ordered (util/ordering[State] provides this)
}

// --------- EXISTING SYSTEM FACTS ----------

fact AdminDefinition {
    all a: Administrator | a.clearance = High and a.isAdmin = True
}

// Only admins can trigger Emergency and must be two distinct admins
fact EmergencyTriggerAdmins {
    all s: State | 
        (s.mode = Emergency) => ( #(s.emAdmins) = 2 and all a: s.emAdmins | a in Administrator )
}

// Emergency privilege assignment only for emAdmins and only in Emergency mode
fact EmergencyPrivilegeAssignment {
    all s: State | 
        all ep: s.emPrivs | 
            ep.admin in s.emAdmins and
            s.mode = Emergency and
            ep.grantedAt = s
}

// Mutual exclusion of roles enforced except in Emergency mode
fact MutualExclusionEnforced {
    all s: State |
        s.mode = Normal =>
            all u: User |
                all r1, r2: Role | 
                    (r1 in rolesHeld(u,s) and r2 in rolesHeld(u,s) and r1 != r2) =>
                        not (r1 in r2.mutuallyExclusiveWith)
}

// Delegated roles only valid until expiresAt (if set), and only for the delegatee
pred rolesHeld(u: User, s: State): set Role {
    { r: Role | some d: s.delegations | d.delegatee = u and d.role = r and (no d.expiresAt or Time/lt[d.delegatedAt, s]) and (no d.expiresAt or Time/lt[s, d.expiresAt]) }
}

// Request classification: always at least as high as the highest object affected
fact RequestClassification {
    all req: Request | 
        req.classification = highestClass(req.affects)
}

pred highestClass(os: set Object): one ClassificationLevel {
    // Abstract: we say all objects have a classification, so the "highest" must exist
    one c: ClassificationLevel | all o: os | c = o.classification or c = C_High or (c = C_Medium and o.classification != C_High)
}

// FIFO is enforced except for high-classification requests in Emergency mode; not modeled at queue level here, but via predicate
fact FIFOEnforcedExceptEmergency {
    all s: State | 
        s.mode = Normal => FIFOProcessing(s)
}

pred FIFOProcessing(s: State) {
    // Abstract: all requests processed in arrival order
    // Not modeling process operation here; see Emergency predicates for bypass
}

// --------- REQUIREMENT PREDICATES ---------

// R1: Emergency Trigger
pred R1 {
    // Emergency can only be triggered from Normal mode, by exactly two admins, joint action
    all s: State | 
        (s.mode = Emergency) => ( #(s.emAdmins) = 2 and prevModeIsNormal(s))
}

pred prevModeIsNormal(s: State) {
    // If s has a predecessor, its mode is Normal
    some Time/prev[s] => Time/prev[s].mode = Normal
}

// R2: Emergency Mode Duration & Termination
pred R1R2 {
    R1 and
    // Emergency mode is bounded: there's a "start" state, then after fixed duration (or early) the mode returns to Normal
    all s: State | 
        (s.mode = Emergency) => (eventuallyReturnsToNormal(s))
}

pred eventuallyReturnsToNormal(s: State) {
    // There exists a future state where mode is Normal, and no intermediate state stays in Emergency forever
    some s': State | Time/gt[s', s] and s'.mode = Normal
}

// Early termination allowed if both emAdmins jointly deactivate Emergency
pred EarlyTermination(s: State) {
    // Mode switches from Emergency to Normal before fixed duration if both emAdmins act
    // Abstract: modeled as possible transition
    prevModeIsEmergency(s) and s.mode = Normal
}

pred prevModeIsEmergency(s: State) {
    some Time/prev[s] => Time/prev[s].mode = Emergency
}

// R3: Emergency Mode Behavior
pred R1R2R3 {
    R1R2 and
    // R3.1: FIFO can be bypassed for high-classification requests
    all s: State | 
        (s.mode = Emergency) => (bypassFIFOForHighClass(s))
    // R3.2: Mutual exclusion of roles suspended
    and
    all s: State | 
        (s.mode = Emergency) => (notMutualExclusionDuringEmergency(s))
    // R3.3: Participating admins have emergency privileges
    and
    all s: State | 
        (s.mode = Emergency) => 
            all a: s.emAdmins | some ep: s.emPrivs | ep.admin = a and ep.grantedAt = s
}

pred bypassFIFOForHighClass(s: State) {
    // Abstract: no ordering enforced on high-classification requests
    // Not modeling request execution; just that it's allowed
    all r: s.requests | 
        (r.classification = C_High) => canBeProcessedOutOfOrder(r, s)
}

pred canBeProcessedOutOfOrder(r: Request, s: State) { 
    // Abstract: always true in Emergency for C_High
    r in s.requests and s.mode = Emergency and r.classification = C_High
}

pred notMutualExclusionDuringEmergency(s: State) {
    // No mutual exclusion enforced on roles
    all u: User | 
        all r1, r2: Role | 
            (r1 in rolesHeld(u,s) and r2 in rolesHeld(u,s)) // No exclusion constraint checked
}

// R4: Post-Emergency Restoration
pred R1R2R3R4 {
    R1R2R3 and
    // R4.1: Emergency privileges revoked from emAdmins after Emergency
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) => 
            all a: Time/prev[s].emAdmins |
                no ep: s.emPrivs | ep.admin = a
    // R4.2: Roles delegated during Emergency revoked after Emergency
    and
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) =>
            all d: s.delegations |
                d.delegatedAt.mode = Emergency => 
                    (d.expiresAt = s) // Must be revoked at this state
    // R4.3: emAdmins must update credentials after Emergency
    and
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) =>
            all a: Time/prev[s].emAdmins |
                a in s.needsCredentialUpdate
}

pred All_Requirements { R1R2R3R4 }

// --------- ASSERTIONS FOR VERIFICATION ---------

// Emergency can only be triggered by exactly two admins, from Normal mode
assert assertR1 {
    all s: State | 
        (s.mode = Emergency) => ( #(s.emAdmins) = 2 and prevModeIsNormal(s) and all a: s.emAdmins | a in Administrator )
}

// Emergency mode is always exited (eventually returns to Normal)
assert assertR2 {
    all s: State |
        (s.mode = Emergency) => (some s': State | Time/gt[s', s] and s'.mode = Normal)
}

// In Emergency, mutual exclusion of roles is suspended
assert assertR3 {
    all s: State |
        (s.mode = Emergency) =>
            all u: User | 
                all r1, r2: Role | 
                    (r1 in rolesHeld(u,s) and r2 in rolesHeld(u,s)) // No exclusion constraint checked
}

// After Emergency, all Emergency privileges are revoked from the two admins who triggered
assert assertR4_1 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) => 
            all a: Time/prev[s].emAdmins |
                no ep: s.emPrivs | ep.admin = a
}

// After Emergency, only delegated roles assigned during Emergency are revoked
assert assertR4_2 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) =>
            all d: s.delegations |
                (d.delegatedAt.mode = Emergency) => d.expiresAt = s
}

// After Emergency, only the two emAdmins need to update credentials
assert assertR4_3 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency(s)) =>
            all a: Time/prev[s].emAdmins | a in s.needsCredentialUpdate
}

// --------- RUN/CHECK COMMANDS ---------
run R1 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
run R1R2 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
run R1R2R3 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
run R1R2R3R4 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
run All_Requirements for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request

check assertR1 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
check assertR2 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
check assertR3 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
check assertR4_1 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
check assertR4_2 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request
check assertR4_3 for 5 but 3 State, 5 User, 3 Administrator, 3 Role, 5 Object, 5 Request

// -- END OF MODEL --