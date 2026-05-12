// RBAC Emergency Module – Alloy 6 (Corrected: next-state operator and temporal predicates)
// STRUCTURE, BEHAVIOR, CONSTRAINTS

open util/ordering[State] as Time

// ===== ENUMS AND MODES =====

abstract sig ClearanceLevel {}
one sig High, Medium, Low extends ClearanceLevel {}

abstract sig ClassificationLevel {}
one sig C_High, C_Medium, C_Low extends ClassificationLevel {}

abstract sig SystemMode {}
one sig Normal, Emergency extends SystemMode {}

// ===== CORE ENTITIES =====

sig User {
    clearance: one ClearanceLevel,
    isAdmin: one Bool
}

sig Administrator in User {}

sig Role {
    mutuallyExclusiveWith: set Role
}

sig Object {
    classification: one ClassificationLevel
}

sig Request {
    requestedBy: one User,
    affects: some Object,
    classification: one ClassificationLevel
}

sig Delegation {
    delegatee: one User,
    role: one Role,
    delegatedAt: one State,
    expiresAt: lone State
}

sig EmergencyPrivilege {
    admin: one Administrator,
    grantedAt: one State,
    revokedAt: lone State
}

// ===== SYSTEM STATE =====

sig State {
    mode: one SystemMode,
    emAdmins: set Administrator, // Admins who triggered Emergency (empty in Normal)
    requests: set Request,
    delegations: set Delegation,
    emPrivs: set EmergencyPrivilege,
    needsCredentialUpdate: set Administrator
}

// ===== TIME ORDERING =====

fact StateOrdering {
    // Provided by util/ordering[State]
}

// ===== EXISTING SYSTEM FACTS =====

// Admins always have High clearance and isAdmin = True
fact AdminDefinition {
    all a: Administrator | a.clearance = High and a.isAdmin = True
}

// Emergency must have exactly two emAdmins (who are Administrators) in Emergency mode
fact EmergencyTriggerAdmins {
    all s: State |
        (s.mode = Emergency) => ( #(s.emAdmins) = 2 and all a: s.emAdmins | a in Administrator )
        and (s.mode = Normal) => no s.emAdmins
}

// EmergencyPrivilege assignment: only emAdmins, only during Emergency, granted at s
fact EmergencyPrivilegeAssignment {
    all s: State |
        all ep: s.emPrivs |
            ep.admin in s.emAdmins
            and s.mode = Emergency
            and ep.grantedAt = s
}

// Mutual exclusion enforced except during Emergency
fact MutualExclusionEnforced {
    all s: State |
        s.mode = Normal =>
            all u: User |
                all r1, r2: Role |
                    (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s] and r1 != r2) =>
                        not (r1 in r2.mutuallyExclusiveWith)
}

// Returns the set of Roles held by user u at state s
fun rolesHeld[u: User, s: State]: set Role {
    { r: Role |
        some d: s.delegations |
            d.delegatee = u and
            d.role = r and
            d.delegatedAt in Time/firsts[s] and
            (no d.expiresAt or Time/lt[s, d.expiresAt])
    }
}

// Request classification reflects highest classification of affected objects
fact RequestClassification {
    all req: Request |
        req.classification = highestClass[req.affects]
}

fun highestClass[os: set Object]: one ClassificationLevel {
    (some o: os | o.classification = C_High) => C_High
    else (some o: os | o.classification = C_Medium) => C_Medium
    else C_Low
}

// FIFO enforced except for C_High requests during Emergency
fact FIFOEnforcedExceptEmergency {
    all s: State |
        s.mode = Normal => FIFOProcessing[s]
}

pred FIFOProcessing[s: State] {
    // Abstract: requests processed in arrival order unless Emergency
}

// ===== REQUIREMENT PREDICATES =====

// R1: Emergency only triggered from Normal mode, by exactly two admins
pred R1 {
    all s: State |
        (s.mode = Emergency) =>
            (#(s.emAdmins) = 2 and prevModeIsNormal[s])
}

pred prevModeIsNormal[s: State] {
    some Time/prev[s] and Time/prev[s].mode = Normal
}

// R2: Emergency mode must eventually return to Normal (bounded duration or early termination)
// Alloy 6 temporal: s' is the next-state of s
pred R1R2 {
    R1 and
    all s: State |
        (s.mode = Emergency) =>
            // There exists a future state after s (possibly not immediately next) with Normal mode
            some s2: State | Time/gt[s2, s] and s2.mode = Normal
}

// Early termination: possible if both emAdmins jointly deactivate Emergency (immediate transition)
pred EarlyTermination[s: State] {
    some Time/prev[s] and Time/prev[s].mode = Emergency and s.mode = Normal
}

// R3: Emergency behavior (FIFO bypass, mutual exclusion suspended, em privileges granted)
pred R1R2R3 {
    R1R2 and
    // R3.1: FIFO can be bypassed for high-classification requests
    all s: State |
        (s.mode = Emergency) => bypassFIFOForHighClass[s]
    and
    // R3.2: Mutual exclusion suspended
    all s: State |
        (s.mode = Emergency) => notMutualExclusionDuringEmergency[s]
    and
    // R3.3: emAdmins have EmergencyPrivilege
    all s: State |
        (s.mode = Emergency) =>
            all a: s.emAdmins | some ep: s.emPrivs | ep.admin = a and ep.grantedAt = s
}

pred bypassFIFOForHighClass[s: State] {
    all r: s.requests |
        (r.classification = C_High) => canBeProcessedOutOfOrder[r, s]
}

pred canBeProcessedOutOfOrder[r: Request, s: State] {
    r in s.requests and s.mode = Emergency and r.classification = C_High
}

pred notMutualExclusionDuringEmergency[s: State] {
    all u: User |
        all r1, r2: Role |
            (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s]) // No exclusion constraint checked during Emergency
}

// R4: Post-Emergency Restoration
pred R1R2R3R4 {
    R1R2R3 and

    // R4.1: emAdmins lose EmergencyPrivilege after Emergency
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins |
                no ep: s.emPrivs | ep.admin = a

    and

    // R4.2: Only delegations assigned during Emergency are revoked when Emergency ends
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all d: s.delegations |
                (d.delegatedAt.mode = Emergency) => (d.expiresAt = s)

    and

    // R4.3: Only the two emAdmins must update credentials after Emergency
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | a in s.needsCredentialUpdate
}

pred prevModeIsEmergency[s: State] {
    some Time/prev[s] and Time/prev[s].mode = Emergency
}

pred All_Requirements { R1R2R3R4 }

// ===== ASSERTIONS FOR VERIFICATION =====

// R1: Emergency only by two admins, from Normal mode
assert assertR1 {
    all s: State |
        (s.mode = Emergency) => (#(s.emAdmins) = 2 and prevModeIsNormal[s] and all a: s.emAdmins | a in Administrator)
}

// R2: Emergency mode is always exited (eventually returns to Normal)
assert assertR2 {
    all s: State |
        (s.mode = Emergency) => (some s2: State | Time/gt[s2, s] and s2.mode = Normal)
}

// R3: In Emergency, mutual exclusion is suspended
assert assertR3 {
    all s: State |
        (s.mode = Emergency) =>
            all u: User |
                all r1, r2: Role |
                    (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s]) // No exclusion constraint checked
}

// R4.1: After Emergency, all EmergencyPrivileges revoked from emAdmins
assert assertR4_1 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins |
                no ep: s.emPrivs | ep.admin = a
}

// R4.2: After Emergency, only Emergency-delegated roles are revoked
assert assertR4_2 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all d: s.delegations |
                (d.delegatedAt.mode = Emergency) => d.expiresAt = s
}

// R4.3: Only emAdmins must update credentials after Emergency
assert assertR4_3 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | a in s.needsCredentialUpdate
}

// ===== RUN/CHECK COMMANDS =====
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

// [LESSON]: Can't declare a variable like 's'' in Alloy 6; must use s' to refer to the next state directly
// [EVENT]: Replaced 'some s': State | Time/gt[s', s] and s'.mode = Normal' with 'some s2: State | Time/gt[s2, s] and s2.mode = Normal' (using closure for "eventually")
// [EVENT]: All uses of the prime operator now refer directly to s' or other state variables; removed all primed variable names