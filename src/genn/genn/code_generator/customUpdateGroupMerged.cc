#include "code_generator/customUpdateGroupMerged.h"

// GeNN code generator includes
#include "code_generator/modelSpecMerged.h"

// GeNN transpiler includes
#include "transpiler/scanner.h"
#include "transpiler/typeChecker.h"
#include "transpiler/parser.h"


using namespace GeNN;
using namespace GeNN::CodeGenerator;
using namespace GeNN::Transpiler;

//--------------------------------------------------------------------------
// Anonymous namespace
//--------------------------------------------------------------------------
namespace
{
template<typename G>
class GroupMergedTypeEnvironment : public TypeChecker::EnvironmentBase
{
public:
    GroupMergedTypeEnvironment(G &groupMerged, const Type::NumericBase *scalarType,
                               TypeChecker::EnvironmentBase *enclosing = nullptr)
    :   m_GroupMerged(groupMerged), m_ScalarType(scalarType), m_Enclosing(enclosing)
    {
    }

    //---------------------------------------------------------------------------
    // EnvironmentBase virtuals
    //---------------------------------------------------------------------------
    virtual void define(const Token &name, const Type::QualifiedType &, ErrorHandlerBase &errorHandler) final
    {
        errorHandler.error(name, "Cannot declare variable in external environment");
        throw TypeCheckError();
    }

    virtual const Type::QualifiedType &assign(const Token &name, Token::Type op, const Type::QualifiedType &assignedType, 
                                              ErrorHandlerBase &errorHandler, bool initializer) final
    {
        // If type isn't found
        auto existingType = m_Types.find(name.lexeme);
        if(existingType == m_Types.end()) {
            if(m_Enclosing) {
                return m_Enclosing->assign(name, op, assignedType, errorHandler, initializer);
            }
            else {
                errorHandler.error(name, "Undefined variable");
                throw TypeCheckError();
            }
        }
    
        // Perform standard type-checking logic
        return EnvironmentBase::assign(name, op, existingType->second, assignedType, errorHandler, initializer);
    }

    virtual const Type::QualifiedType &incDec(const Token &name, Token::Type op, ErrorHandlerBase &errorHandler) final
    {
        auto existingType = m_Types.find(name.lexeme);
        if(existingType == m_Types.end()) {
            if(m_Enclosing) {
                return m_Enclosing->incDec(name, op, errorHandler);
            }
            else {
                errorHandler.error(name, "Undefined variable");
                throw TypeCheckError();
            }
        }
    
        // Perform standard type-checking logic
        return EnvironmentBase::incDec(name, op, existingType->second, errorHandler);
    
    }

    virtual const Type::QualifiedType &getType(const Token &name, ErrorHandlerBase &errorHandler) final
    {
        auto type = m_Types.find(std::string{name.lexeme});
        if(type == m_Types.end()) {
            if(m_Enclosing) {
                return m_Enclosing->getType(name, errorHandler);
            }
            else {
                errorHandler.error(name, "Undefined variable");
                throw TypeCheckError();
            }
        }
        else {
            return type->second;
        }
    }

    //---------------------------------------------------------------------------
    // Public API
    //---------------------------------------------------------------------------
    void define(std::string_view name, const Type::Base *type, bool isConstValue = false, bool isConstPointer = false)
    {
        if(!m_Types.try_emplace(name, type, isConstValue, isConstPointer).second) {
            throw std::runtime_error("Redeclaration of '" + std::string{name} + "'");
        }
    }
    template<typename T>
    void define(std::string_view name, bool isConstValue = false, bool isConstPointer = false)
    {
        define(name, T::getInstance(), isConstValue, isConstPointer);
    }

    template<typename T, typename P, typename H>
    void addHeterogeneousParams(const Snippet::Base::StringVec &paramNames, const std::string &suffix,
                                P getParamValues, H isHeterogeneous)
    {
        // Loop through params
        for(const auto &p : paramNames) {
            // Define constant
            define(p + suffix, m_ScalarType, true);

            // If parameters is heterogeneous
            if((static_cast<const T*>(this)->*isHeterogeneous)(p)) {
                // Add field
                m_GroupMerged->addScalarField(p + suffix,
                                              [p, getParamValues](const G &g, size_t)
                                              {
                                                  const auto &values = getParamValues(g);
                                                  return Utils::writePreciseString(values.at(p));
                                              });
            }
        }
    }

    template<typename T, typename D, typename H>
    void addHeterogeneousDerivedParams(const Snippet::Base::DerivedParamVec &derivedParams, const std::string &suffix,
                                       D getDerivedParamValues, H isHeterogeneous)
    {
        // Loop through derived params
        for(const auto &d : derivedParams) {
            // If parameters isn't homogeneous
            if((static_cast<const T*>(this)->*isHeterogeneous)(d.name)) {
                // Define constant
                define(p + suffix, m_ScalarType, true);

                // Add field
                addScalarField(d.name + suffix,
                               [d, getDerivedParamValues](const G &g, size_t)
                               {
                                   const auto &values = getDerivedParamValues(g);
                                   return Utils::writePreciseString(values.at(d.name));
                               });
            }
        }
    }

private:
    //---------------------------------------------------------------------------
    // Members
    //---------------------------------------------------------------------------
    G &m_GroupMerged;
    const Type::NumericBase *m_ScalarType;
    TypeChecker::EnvironmentBase *m_Enclosing;

    std::unordered_map<std::string_view, Type::QualifiedType> m_Types;
};

template<typename C, typename R>
void genCustomUpdate(CodeStream &os, Substitutions &baseSubs, const C &cg, 
                     const ModelSpecMerged &modelMerged, const std::string &index,
                     R getVarRefIndex)
{
    Substitutions updateSubs(&baseSubs);

    const CustomUpdateModels::Base *cm = cg.getArchetype().getCustomUpdateModel();
    const auto varRefs = cm->getVarRefs();

    // Loop through variables
    for(const auto &v : cm->getVars()) {
        if(v.access & VarAccessMode::READ_ONLY) {
            os << "const ";
        }
        os << v.type << " l" << v.name;
        
        // If this isn't a reduction, read value from memory
        // **NOTE** by not initialising these variables for reductions, 
        // compilers SHOULD emit a warning if user code doesn't set it to something
        if(!(v.access & VarAccessModeAttribute::REDUCE)) {
            os << " = group->" << v.name << "[";
            os << cg.getVarIndex(getVarAccessDuplication(v.access),
                                 updateSubs[index]);
            os << "]";
        }
        os << ";" << std::endl;
    }

    // Loop through variable references
    for(const auto &v : varRefs) {
        if(v.access == VarAccessMode::READ_ONLY) {
            os << "const ";
        }
       
        os << v.type << " l" << v.name;
        
        // If this isn't a reduction, read value from memory
        // **NOTE** by not initialising these variables for reductions, 
        // compilers SHOULD emit a warning if user code doesn't set it to something
        if(!(v.access & VarAccessModeAttribute::REDUCE)) {
            os << " = " << "group->" << v.name << "[";
            os << getVarRefIndex(cg.getArchetype().getVarReferences().at(v.name),
                                 updateSubs[index]);
            os << "]";
        }
        os << ";" << std::endl;
    }
    
    updateSubs.addVarNameSubstitution(cm->getVars(), "", "l");
    updateSubs.addVarNameSubstitution(cm->getVarRefs(), "", "l");
    updateSubs.addParamValueSubstitution(cm->getParamNames(), cg.getArchetype().getParams(),
                                         [&cg](const std::string &p) { return cg.isParamHeterogeneous(p);  },
                                         "", "group->");
    updateSubs.addVarValueSubstitution(cm->getDerivedParams(), cg.getArchetype().getDerivedParams(),
                                       [&cg](const std::string &p) { return cg.isDerivedParamHeterogeneous(p);  },
                                       "", "group->");
    updateSubs.addVarNameSubstitution(cm->getExtraGlobalParams(), "", "group->");

    std::string code = cm->getUpdateCode();
    updateSubs.applyCheckUnreplaced(code, "custom update : merged" + std::to_string(cg.getIndex()));
    code = ensureFtype(code, modelMerged.getModel().getPrecision());
    os << code;

    // Write read/write variables back to global memory
    for(const auto &v : cm->getVars()) {
        if(v.access & VarAccessMode::READ_WRITE) {
            os << "group->" << v.name << "[";
            os << cg.getVarIndex(getVarAccessDuplication(v.access),
                                 updateSubs[index]);
            os << "] = l" << v.name << ";" << std::endl;
        }
    }

    // Write read/write variable references back to global memory
    for(const auto &v : varRefs) {
        if(v.access == VarAccessMode::READ_WRITE) {
            os << "group->" << v.name << "[";
            os << getVarRefIndex(cg.getArchetype().getVarReferences().at(v.name),
                                 updateSubs[index]);
            os << "] = l" << v.name << ";" << std::endl;
        }
    }
}
}   // Anonymous namespace

//----------------------------------------------------------------------------
// GeNN::CodeGenerator::CustomUpdateGroupMerged
//----------------------------------------------------------------------------
const std::string CustomUpdateGroupMerged::name = "CustomUpdate";
//----------------------------------------------------------------------------
CustomUpdateGroupMerged::CustomUpdateGroupMerged(size_t index, const std::string &precision, const std::string&, const BackendBase &backend,
                                                 const std::vector<std::reference_wrapper<const CustomUpdateInternal>> &groups)
:   GroupMerged<CustomUpdateInternal>(index, precision, groups)
{
    // Create type environment
    // **TEMP** parse precision to get scalar type
    GroupMergedTypeEnvironment<CustomUpdateGroupMerged> typeEnvironment(this, Type::parseNumeric(precision));

    addField("unsigned int", "size",
             [](const CustomUpdateInternal &c, size_t) { return std::to_string(c.getSize()); });
    
    // If some variables are delayed, add delay pointer
    if(getArchetype().getDelayNeuronGroup() != nullptr) {
        addField("unsigned int*", "spkQuePtr", 
                 [&backend](const CustomUpdateInternal &cg, size_t) 
                 { 
                     return backend.getScalarAddressPrefix() + "spkQuePtr" + cg.getDelayNeuronGroup()->getName(); 
                 });
    }

    // Add heterogeneous custom update model parameters
    const CustomUpdateModels::Base *cm = getArchetype().getCustomUpdateModel();
    typeEnvironment.addHeterogeneousParams<CustomUpdateGroupMerged>(
        cm->getParamNames(), "",
        [](const CustomUpdateInternal &cg) { return cg.getParams(); },
        &CustomUpdateGroupMerged::isParamHeterogeneous);

    // Add heterogeneous weight update model derived parameters
    typeEnvironment.addHeterogeneousDerivedParams<CustomUpdateGroupMerged>(
        cm->getDerivedParams(), "",
        [](const CustomUpdateInternal &cg) { return cg.getDerivedParams(); },
        &CustomUpdateGroupMerged::isDerivedParamHeterogeneous);

    // Add variables to struct
    addVars(cm->getVars(), backend.getDeviceVarPrefix());

    // Add variable references to struct
    addVarReferences(cm->getVarRefs(), backend.getDeviceVarPrefix(),
                    [](const CustomUpdateInternal &cg) { return cg.getVarReferences(); });

    // Add EGPs to struct
    this->addEGPs(cm->getExtraGlobalParams(), backend.getDeviceVarPrefix());
}
//----------------------------------------------------------------------------
bool CustomUpdateGroupMerged::isParamHeterogeneous(const std::string &paramName) const
{
    return isParamValueHeterogeneous(paramName, [](const CustomUpdateInternal &cg) { return cg.getParams(); });
}
//----------------------------------------------------------------------------    
bool CustomUpdateGroupMerged::isDerivedParamHeterogeneous(const std::string &paramName) const
{
    return isParamValueHeterogeneous(paramName, [](const CustomUpdateInternal &cg) { return cg.getDerivedParams(); });
}
//----------------------------------------------------------------------------
boost::uuids::detail::sha1::digest_type CustomUpdateGroupMerged::getHashDigest() const
{
    boost::uuids::detail::sha1 hash;

    // Update hash with archetype's hash digest
    Utils::updateHash(getArchetype().getHashDigest(), hash);

    // Update hash with each group's custom update size
    updateHash([](const CustomUpdateInternal &cg) { return cg.getSize(); }, hash);

    // Update hash with each group's parameters, derived parameters and variable references
    updateHash([](const CustomUpdateInternal &cg) { return cg.getParams(); }, hash);
    updateHash([](const CustomUpdateInternal &cg) { return cg.getDerivedParams(); }, hash);
    updateHash([](const CustomUpdateInternal &cg) { return cg.getVarReferences(); }, hash);

    return hash.get_digest();
}
//----------------------------------------------------------------------------
void CustomUpdateGroupMerged::generateCustomUpdate(const BackendBase&, CodeStream &os, const ModelSpecMerged &modelMerged, Substitutions &popSubs) const
{
    genCustomUpdate(os, popSubs, *this, modelMerged, "id",
                    [this](const Models::VarReference &varRef, const std::string &index)
                    {
                        return getVarRefIndex(varRef.getDelayNeuronGroup() != nullptr,
                                              getVarAccessDuplication(varRef.getVar().access),
                                              index);
                    });
}
//----------------------------------------------------------------------------
std::string CustomUpdateGroupMerged::getVarIndex(VarAccessDuplication varDuplication, const std::string &index) const
{
    // **YUCK** there's a lot of duplication in these methods - do they belong elsewhere?
    if (varDuplication == VarAccessDuplication::SHARED_NEURON) {
        return getArchetype().isBatched() ? "batch" : "0";
    }
    else if (varDuplication == VarAccessDuplication::SHARED || !getArchetype().isBatched()) {
        assert(!index.empty());
        return index;
    }
    else {
        assert(!index.empty());
        return "batchOffset + " + index;
    }
}
//----------------------------------------------------------------------------
std::string CustomUpdateGroupMerged::getVarRefIndex(bool delay, VarAccessDuplication varDuplication, const std::string &index) const
{
    // If delayed, variable is shared, the batch size is one or this custom update isn't batched, batch delay offset isn't required
    if(delay) {
        if (varDuplication == VarAccessDuplication::SHARED_NEURON) {
            return getArchetype().isBatched() ? "batchDelaySlot" : "delaySlot";
        }
        else if (varDuplication == VarAccessDuplication::SHARED || !getArchetype().isBatched()) {
            assert(!index.empty());
            return "delayOffset + " + index;
        }
        else {
            assert(!index.empty());
            return "batchDelayOffset + " + index;
        }
    }
    else {
        return getVarIndex(varDuplication, index);
    }    
}

// ----------------------------------------------------------------------------
// GeNN::CodeGenerator::CustomUpdateWUGroupMergedBase
//----------------------------------------------------------------------------
bool CustomUpdateWUGroupMergedBase::isParamHeterogeneous(const std::string &paramName) const
{
    return isParamValueHeterogeneous(paramName, [](const CustomUpdateWUInternal &cg) { return cg.getParams(); });
}
//----------------------------------------------------------------------------
bool CustomUpdateWUGroupMergedBase::isDerivedParamHeterogeneous(const std::string &paramName) const
{
    return isParamValueHeterogeneous(paramName, [](const CustomUpdateWUInternal &cg) { return cg.getDerivedParams(); });
}
//----------------------------------------------------------------------------
boost::uuids::detail::sha1::digest_type CustomUpdateWUGroupMergedBase::getHashDigest() const
{
    boost::uuids::detail::sha1 hash;

    // Update hash with archetype's hash digest
    Utils::updateHash(getArchetype().getHashDigest(), hash);

    // Update hash with sizes of pre and postsynaptic neuron groups
    updateHash([](const CustomUpdateWUInternal &cg) 
               {
                   return static_cast<const SynapseGroupInternal*>(cg.getSynapseGroup())->getSrcNeuronGroup()->getNumNeurons();
               }, hash);

    updateHash([](const CustomUpdateWUInternal &cg) 
               {
                   return static_cast<const SynapseGroupInternal*>(cg.getSynapseGroup())->getTrgNeuronGroup()->getNumNeurons();
               }, hash);

    // Update hash with each group's parameters, derived parameters and variable referneces
    updateHash([](const CustomUpdateWUInternal &cg) { return cg.getParams(); }, hash);
    updateHash([](const CustomUpdateWUInternal &cg) { return cg.getDerivedParams(); }, hash);
    updateHash([](const CustomUpdateWUInternal &cg) { return cg.getVarReferences(); }, hash);

    return hash.get_digest();
}
//----------------------------------------------------------------------------
std::string CustomUpdateWUGroupMergedBase::getVarIndex(VarAccessDuplication varDuplication, const std::string &index) const
{
    // **YUCK** there's a lot of duplication in these methods - do they belong elsewhere?
    return ((varDuplication == VarAccessDuplication::SHARED || !getArchetype().isBatched()) ? "" : "batchOffset + ") + index;
}
//----------------------------------------------------------------------------
std::string CustomUpdateWUGroupMergedBase::getVarRefIndex(VarAccessDuplication varDuplication, const std::string &index) const
{
    // **YUCK** there's a lot of duplication in these methods - do they belong elsewhere?
    return ((varDuplication == VarAccessDuplication::SHARED || !getArchetype().isBatched()) ? "" : "batchOffset + ") + index;
}
//----------------------------------------------------------------------------
CustomUpdateWUGroupMergedBase::CustomUpdateWUGroupMergedBase(size_t index, const std::string &precision, const std::string &, const BackendBase &backend,
                                                             const std::vector<std::reference_wrapper<const CustomUpdateWUInternal>> &groups)
:   GroupMerged<CustomUpdateWUInternal>(index, precision, groups)
{
    // If underlying synapse group has kernel weights
    if (getArchetype().getSynapseGroup()->getMatrixType() & SynapseMatrixWeight::KERNEL) {
        // Loop through kernel size dimensions
        for (size_t d = 0; d < getArchetype().getSynapseGroup()->getKernelSize().size(); d++) {
            // If this dimension has a heterogeneous size, add it to struct
            if (isKernelSizeHeterogeneous(d)) {
                addField("unsigned int", "kernelSize" + std::to_string(d),
                         [d](const CustomUpdateWUInternal &cu, size_t) 
                         {
                             return std::to_string(cu.getSynapseGroup()->getKernelSize().at(d));
                         });
            }
        }
    }
    // Otherwise
    else {
        addField("unsigned int", "rowStride",
                 [&backend](const CustomUpdateWUInternal &cg, size_t) 
                 { 
                     const SynapseGroupInternal *sgInternal = static_cast<const SynapseGroupInternal*>(cg.getSynapseGroup());
                     return std::to_string(backend.getSynapticMatrixRowStride(*sgInternal)); 
                 });
    
        addField("unsigned int", "numSrcNeurons",
                 [](const CustomUpdateWUInternal &cg, size_t) 
                 {
                     const SynapseGroupInternal *sgInternal = static_cast<const SynapseGroupInternal*>(cg.getSynapseGroup());
                     return std::to_string(sgInternal->getSrcNeuronGroup()->getNumNeurons()); 
                 });

        addField("unsigned int", "numTrgNeurons",
                 [](const CustomUpdateWUInternal &cg, size_t)
                 { 
                     const SynapseGroupInternal *sgInternal = static_cast<const SynapseGroupInternal*>(cg.getSynapseGroup());
                     return std::to_string(sgInternal->getTrgNeuronGroup()->getNumNeurons()); 
                 });

        // If synapse group has sparse connectivity
        if(getArchetype().getSynapseGroup()->getMatrixType() & SynapseMatrixConnectivity::SPARSE) {
            addField(getArchetype().getSynapseGroup()->getSparseIndType() + "*", "ind", 
                     [&backend](const CustomUpdateWUInternal &cg, size_t) 
                     { 
                         return backend.getDeviceVarPrefix() + "ind" + cg.getSynapseGroup()->getName(); 
                     });

            addField("unsigned int*", "rowLength",
                    [&backend](const CustomUpdateWUInternal &cg, size_t) 
                    { 
                        return backend.getDeviceVarPrefix() + "rowLength" + cg.getSynapseGroup()->getName(); 
                    });
        }
    }

    // Add heterogeneous custom update model parameters
    const CustomUpdateModels::Base *cm = getArchetype().getCustomUpdateModel();
    addHeterogeneousParams<CustomUpdateWUGroupMerged>(
        cm->getParamNames(), "",
        [](const CustomUpdateWUInternal &cg) { return cg.getParams(); },
        &CustomUpdateWUGroupMergedBase::isParamHeterogeneous);

    // Add heterogeneous weight update model derived parameters
    addHeterogeneousDerivedParams<CustomUpdateWUGroupMerged>(
        cm->getDerivedParams(), "",
        [](const CustomUpdateWUInternal &cg) { return cg.getDerivedParams(); },
        &CustomUpdateWUGroupMergedBase::isDerivedParamHeterogeneous);

    // Add variables to struct
    addVars(cm->getVars(), backend.getDeviceVarPrefix());

    // Add variable references to struct
    const auto varRefs = cm->getVarRefs();
    addVarReferences(varRefs, backend.getDeviceVarPrefix(),
                     [](const CustomUpdateWUInternal &cg) { return cg.getVarReferences(); });

     // Loop through variables
    for(const auto &v : varRefs) {
        // If variable has a transpose 
        if(getArchetype().getVarReferences().at(v.name).getTransposeSynapseGroup() != nullptr) {
            // Add field with transpose suffix, pointing to transpose var
            addField(v.type + "*", v.name + "Transpose",
                     [&backend, v](const CustomUpdateWUInternal &g, size_t)
                     {
                         const auto varRef = g.getVarReferences().at(v.name);
                         return backend.getDeviceVarPrefix() + varRef.getTransposeVar().name + varRef.getTransposeTargetName();
                     });
            }
    }
    // Add EGPs to struct
    this->addEGPs(cm->getExtraGlobalParams(), backend.getDeviceVarPrefix());
}

// ----------------------------------------------------------------------------
// GeNN::CodeGenerator::CustomUpdateWUGroupMerged
//----------------------------------------------------------------------------
const std::string CustomUpdateWUGroupMerged::name = "CustomUpdateWU";
//----------------------------------------------------------------------------
void CustomUpdateWUGroupMerged::generateCustomUpdate(const BackendBase&, CodeStream &os, const ModelSpecMerged &modelMerged, Substitutions &popSubs) const
{
    genCustomUpdate(os, popSubs, *this, modelMerged, "id_syn",
                    [this, &modelMerged](const Models::WUVarReference &varRef, const std::string &index) 
                    {  
                        return getVarRefIndex(getVarAccessDuplication(varRef.getVar().access),
                                              index);
                    });
}

//----------------------------------------------------------------------------
// CustomUpdateTransposeWUGroupMerged
//----------------------------------------------------------------------------
const std::string CustomUpdateTransposeWUGroupMerged::name = "CustomUpdateTransposeWU";
//----------------------------------------------------------------------------
void CustomUpdateTransposeWUGroupMerged::generateCustomUpdate(const BackendBase&, CodeStream &os, const ModelSpecMerged &modelMerged, Substitutions &popSubs) const
{
    genCustomUpdate(os, popSubs, *this, modelMerged, "id_syn",
                    [this, &modelMerged](const Models::WUVarReference &varRef, const std::string &index) 
                    {
                        return getVarRefIndex(getVarAccessDuplication(varRef.getVar().access),
                                              index);
                    });
}

// ----------------------------------------------------------------------------
// CustomUpdateHostReductionGroupMerged
//----------------------------------------------------------------------------
const std::string CustomUpdateHostReductionGroupMerged::name = "CustomUpdateHostReduction";
//----------------------------------------------------------------------------
CustomUpdateHostReductionGroupMerged::CustomUpdateHostReductionGroupMerged(size_t index, const std::string &precision, const std::string &, const BackendBase &backend,
                                                                           const std::vector<std::reference_wrapper<const CustomUpdateInternal>> &groups)
:   CustomUpdateHostReductionGroupMergedBase<CustomUpdateInternal>(index, precision, backend, groups)
{
    addField("unsigned int", "size",
             [](const CustomUpdateInternal &c, size_t) { return std::to_string(c.getSize()); });

    // If some variables are delayed, add delay pointer
    // **NOTE** this is HOST delay pointer
    if(getArchetype().getDelayNeuronGroup() != nullptr) {
        addField("unsigned int*", "spkQuePtr", 
                 [&](const CustomUpdateInternal &cg, size_t) 
                 { 
                     return "spkQuePtr" + cg.getDelayNeuronGroup()->getName(); 
                 });
    }
}

// ----------------------------------------------------------------------------
// CustomWUUpdateHostReductionGroupMerged
//----------------------------------------------------------------------------
const std::string CustomWUUpdateHostReductionGroupMerged::name = "CustomWUUpdateHostReduction";
//----------------------------------------------------------------------------
CustomWUUpdateHostReductionGroupMerged::CustomWUUpdateHostReductionGroupMerged(size_t index, const std::string &precision, const std::string &, const BackendBase &backend,
                                                                               const std::vector<std::reference_wrapper<const CustomUpdateWUInternal>> &groups)
:   CustomUpdateHostReductionGroupMergedBase<CustomUpdateWUInternal>(index, precision, backend, groups)
{
    addField("unsigned int", "size",
             [&backend](const CustomUpdateWUInternal &cg, size_t) 
             {
                 return std::to_string(cg.getSynapseGroup()->getMaxConnections() * (size_t)cg.getSynapseGroup()->getSrcNeuronGroup()->getNumNeurons()); 
             });
}
